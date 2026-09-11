"""Validate and hand off Codex batches using a dedicated, clean checkout.

Uses existing Git authentication. Never stores credentials, force pushes, stashes,
or commits unrelated work. The destination is the user-authorized private repo.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/BillShiyaoZhang/job-hunting.git'
CHECKOUT = ROOT / '.local/codex-sync'
LOCK = ROOT / '.local/codex-sync.lock'


def command(args, cwd=ROOT):
    result = subprocess.run(args, cwd=cwd, env={**os.environ, 'GIT_TERMINAL_PROMPT':'0', 'GCM_INTERACTIVE':'Never'}, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    if result.returncode:
        # Never echo arbitrary credential-helper output or authorization headers.
        raise RuntimeError(f"Command failed: {args[0]} {args[-1] if args[0] == sys.executable else '(git operation)'}. Check Git authentication, branch protection, and repository status; no files were discarded.")
    return result.stdout.strip()


def git(*args):
    return command(['git', '-c', f'safe.directory={CHECKOUT.as_posix()}', *args], CHECKOUT)


def prepare():
    if not CHECKOUT.exists():
        command(['git', 'clone', '--depth', '1', '--branch', 'main', '--', REPO, str(CHECKOUT)])
    if not (CHECKOUT / '.git').is_dir():
        raise ValueError('Dedicated checkout path exists but is not a Git repository; it was not overwritten.')
    if git('remote', 'get-url', 'origin') != REPO or git('branch', '--show-current') != 'main':
        raise ValueError('Dedicated checkout does not match the authorized repository and main branch.')
    if git('status', '--porcelain'):
        raise ValueError('Dedicated checkout has changes from a previous run. Review them; nothing was stashed or discarded.')
    git('fetch', 'origin', 'main')
    git('merge', '--ff-only', 'origin/main')
    if git('rev-parse', 'HEAD') != git('rev-parse', 'origin/main'):
        raise ValueError('Dedicated checkout has unpublished commits; review and resolve before retrying.')


def import_batches(batches):
    # Execute the latest checkout's validators. Read and validate every batch
    # before writing any, so a bad later batch cannot strand a dirty checkout.
    program = '''
import hashlib, json, sys
from jobradar.core import ROOT, load_config, read_json, write_json
from jobradar.pipeline import validate_batch
config = load_config()
values = [read_json(path) for path in sys.argv[1:]]
for value in values:
    validate_batch(value, config)
targets = []
for value in values:
    digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]
    target = f"data/inbox/{value['source_id']}-{digest}.json"
    write_json(ROOT / target, value)
    targets.append(target)
print(json.dumps(targets))
'''
    return json.loads(command([sys.executable, '-X', 'utf8', '-c', program, *map(str, batches)], CHECKOUT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='Only initialize/sync the isolated checkout; no remote writes')
    parser.add_argument('--batch', nargs='+', type=Path, help='Validated Codex JSON files to import and push')
    args = parser.parse_args()
    if not args.prepare and not args.batch:
        parser.error('Specify --prepare or --batch')
    batches = [p.resolve(strict=True) for p in args.batch or []]
    if any(p.stat().st_size > 1_000_000 for p in batches):
        raise ValueError('A batch exceeds 1 MB')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOCK.open('x', encoding='utf-8') as lock:
            lock.write(str(os.getpid()))
    except FileExistsError:
        raise ValueError('Another handoff is running or a previous lock needs review.')
    try:
        prepare()
        if not batches:
            print(json.dumps({'status':'ready','checkout':str(CHECKOUT)}, ensure_ascii=False))
            return
        command([sys.executable, '-X', 'utf8', '-m', 'jobradar', 'validate'], CHECKOUT)
        targets = import_batches(batches)
        git('add', '--', *targets)
        staged = git('diff', '--cached', '--name-only').splitlines()
        if not staged:
            print(json.dumps({'status':'unchanged','files':targets}))
            return
        if set(staged) - set(targets):
            raise ValueError('Unexpected staged files; commit and push were refused.')
        git('-c', 'user.name=job-radar-codex', '-c', 'user.email=job-radar-codex@users.noreply.github.com', 'commit', '-m', 'chore: add verified Codex job batches')
        git('push', 'origin', 'HEAD:main')
        print(json.dumps({'status':'pushed','commit':git('rev-parse','HEAD'),'files':targets}))
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
