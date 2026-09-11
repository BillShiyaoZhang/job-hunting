"""Attach current stage outcomes; never mislabel a previous collector report."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
local = root / '.local'
local.mkdir(exist_ok=True)
start_file = local / 'workflow-start.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def timestamp():
    return datetime.now(timezone.utc).isoformat()


if sys.argv[1] == 'start':
    start_file.write_text(json.dumps({'started_at': timestamp()}), encoding='utf-8')
elif sys.argv[1] == 'finish':
    start = read(start_file)
    latest = read(root / 'data/runs/latest.json')
    current = bool(start and latest and datetime.fromisoformat(latest['started_at'].replace('Z', '+00:00')) >= datetime.fromisoformat(start['started_at']).replace(microsecond=0))
    steps = json.loads(os.environ.get('JOBRADAR_STEPS', '{}'))
    report = {
        'workflow_run_id': os.environ.get('GITHUB_RUN_ID'),
        'workflow_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'started_at': start['started_at'] if start else None,
        'reported_at': timestamp(),
        'stages': {key: {k: value.get(k) for k in ('outcome', 'conclusion')} for key, value in steps.items()},
        'collector_report_is_current': current,
        'collector_report': latest if current else None,
        'note': '本轮阶段结果；collector_report 为空表示采集未产生本轮报告，请查看失败步骤日志。',
    }
    (local / 'workflow-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
else:
    raise SystemExit('Expected start or finish')
