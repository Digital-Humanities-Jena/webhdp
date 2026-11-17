#!/usr/bin/env python3
"""Capture read-only scheduler evidence for an isolated reconstruction validation job."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

FIELDS = ('JobId', 'JobName', 'JobState', 'Reason', 'Partition', 'TimeLimit',
          'SubmitTime', 'StartTime', 'EndTime', 'NumNodes', 'NumCPUs',
          'ReqTRES', 'AllocTRES', 'TresPerNode', 'SchedNodeList', 'NodeList')


def capture(job_id: str, host: str = 'draco') -> dict:
    if not re.fullmatch(r'[1-9][0-9]*', job_id):
        raise ValueError('A numeric Slurm job ID is required')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', host) or host.startswith('-'):
        raise ValueError('A configured SSH host alias is required')
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host,
               'scontrol', 'show', 'job', job_id, '-o']
    completed = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
    fields = dict(re.findall(r'(\w+)=(\S+)', completed.stdout))
    if fields.get('JobId') != job_id:
        raise ValueError('Scheduler returned a different job')
    return {'observed_at': datetime.now(UTC).isoformat(),
            **{key: fields[key] for key in FIELDS if key in fields},
            'start_time_is_estimate': fields.get('JobState') == 'PENDING',
            'scope': 'isolated validation; no deployment',
            'scheduler_evidence_only': True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--host', default='draco')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = capture(args.job_id, args.host)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({key: evidence.get(key) for key in
                      ('JobId', 'JobState', 'Partition', 'StartTime', 'start_time_is_estimate')}))


if __name__ == '__main__':
    main()
