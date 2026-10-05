"""Persist remote operation intent before requests with uncertain acknowledgements."""

import json
from datetime import datetime, timezone
from uuid import uuid4


def pending_operation(cursor, record_id, operation_type):
    row = cursor.execute("""SELECT * FROM zenodo_remote_operations
        WHERE record_id = ? AND operation_type = ? AND state = 'uncertain'
        ORDER BY created_at DESC LIMIT 1""", (record_id, operation_type)).fetchone()
    return dict(row) if row else None


def pending_operations(cursor, record_id):
    return [operation_summary(dict(row)) for row in cursor.execute("""
        SELECT * FROM zenodo_remote_operations WHERE record_id = ? AND state = 'uncertain'
        ORDER BY created_at""", (record_id,)).fetchall()]


def operation_summary(operation):
    return {key: operation.get(key) for key in
            ('operation_id', 'operation_type', 'state', 'remote_id', 'error', 'created_at', 'updated_at')}


def begin_operation(conn, record_id, operation_type, payload, *, remote_id=None):
    now = datetime.now(timezone.utc).isoformat()
    operation = dict(operation_id=str(uuid4()), record_id=record_id,
                     operation_type=operation_type, state='uncertain',
                     request_json=json.dumps(payload), remote_id=remote_id,
                     created_at=now, updated_at=now)
    conn.execute("""INSERT INTO zenodo_remote_operations
        (operation_id, record_id, operation_type, state, request_json, remote_id, created_at, updated_at)
        VALUES (:operation_id, :record_id, :operation_type, :state, :request_json, :remote_id, :created_at, :updated_at)""", operation)
    conn.commit()
    return operation


def record_response(conn, operation, payload):
    remote_id = str(payload.get('id') or operation.get('remote_id') or '') or None
    conn.execute("""UPDATE zenodo_remote_operations SET remote_id = ?, response_json = ?, updated_at = ?
        WHERE operation_id = ?""", (remote_id, json.dumps(payload), datetime.now(timezone.utc).isoformat(), operation['operation_id']))
    conn.commit()
    operation.update(remote_id=remote_id, response_json=json.dumps(payload))


def finish_operation(cursor, operation, *, state='completed', error=None):
    cursor.execute("""UPDATE zenodo_remote_operations SET state = ?, error = ?, updated_at = ?
        WHERE operation_id = ?""", (state, error, datetime.now(timezone.utc).isoformat(), operation['operation_id']))


def uncertain_result(conn, operation, error=None):
    message = ('Zenodo may have accepted this request. Check its remote state and reconnect '
               'from the record details before retrying.')
    # Request exceptions can include URLs containing access tokens.
    operation['error'] = (f'The remote response could not be verified ({type(error).__name__}).'
                          if isinstance(error, Exception) else str(error or message))
    conn.execute("UPDATE zenodo_remote_operations SET error = ?, updated_at = ? WHERE operation_id = ?",
                 (operation['error'], datetime.now(timezone.utc).isoformat(), operation['operation_id']))
    conn.execute("UPDATE zenodo_records SET last_api_error = ? WHERE record_id = ?",
                 (json.dumps({'code': 'REMOTE_OUTCOME_UNCERTAIN', 'message': message}), operation['record_id']))
    conn.commit()
    return {'success': False, 'error_code': 'REMOTE_OUTCOME_UNCERTAIN', 'error': message,
            'reconciliation_required': True, 'operation': operation_summary(operation)}
