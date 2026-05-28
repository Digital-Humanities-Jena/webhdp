# Restore Drill Checklist

Use this checklist before the first public deployment and after meaningful backup changes.

## Preparation

- Confirm `BACKUP_ENCRYPTION_KEY` is available to the operator.
- Confirm the backup archive and manifest are present locally or in Dropbox.
- Stop backend and worker services before restoring into a live deployment.
- Choose an isolated restore target for drills, for example `/tmp/webhdp-restore-drill`.

## Drill Commands

```bash
./scripts/list_backups.py
./scripts/backup_status.py
./scripts/restore_drill.py backups/<archive>.tar.gz.enc --target-root /tmp/webhdp-restore-drill
```

## Verification

- `instance/hdp_web.db` exists in the restore target.
- Session data exists under `hdp-shared/sessions` when the source backup contained sessions.
- `local_input` and `local_output` were restored when present.
- Credential files were restored only when intentionally included and encrypted.
- The restored SQLite database opens successfully.
- The restore drill reports verified paths/files and `PRAGMA integrity_check = ok`.

Example SQLite check:

```bash
sqlite3 /tmp/webhdp-restore-drill/instance/hdp_web.db 'PRAGMA integrity_check;'
```

## Record

Record the date, archive filename, restore target, result, and any follow-up actions in the operations notes.
