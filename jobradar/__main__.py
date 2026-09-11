import argparse
import json
import sys
from pathlib import Path

from .core import ROOT, load_config, read_json, write_json
from .pipeline import build, collect, load_batches, plan, validate_batch, validate_dataset


def main():
    parser = argparse.ArgumentParser(description="工作雷达：检索、核验和静态构建（Python 3.11+）")
    parser.add_argument("--config", default=str(ROOT / "config/search.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="校验配置、已有数据及 inbox")
    sub.add_parser("plan", help="输出每个启用来源的最终策略和 Codex 搜索词")
    sub.add_parser("collect", help="采集启用来源并合并 Codex inbox")
    cmd = sub.add_parser("build", help="准备 dist 静态数据")
    cmd.add_argument("--production", action="store_true", help="拒绝示例数据")
    cmd = sub.add_parser("demo", help="生成明确标记的虚构示例")
    cmd.add_argument("--force", action="store_true")
    cmd = sub.add_parser("import", help="校验并导入一个 Codex 批次（仅本地）")
    cmd.add_argument("file")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.command == "validate":
            if (ROOT / "data/jobs.json").exists():
                validate_dataset(read_json(ROOT / "data/jobs.json"))
            batches = load_batches(config, ROOT / "data/inbox")
            print(f"OK: {len(config['sources'])} sources, {len(batches)} inbox batches")
        elif args.command == "plan":
            print(json.dumps(plan(config), ensure_ascii=False, indent=2))
        elif args.command == "collect":
            run = collect(config)
            print(json.dumps(run, ensure_ascii=False, indent=2))
            return 1 if run["status"] == "error" else 0
        elif args.command == "build":
            print(f"Built dist: {build(config, production=args.production)} jobs")
        elif args.command == "demo":
            from .demo import create_demo
            create_demo(config, force=args.force)
            print(f"Demo ready: {build(config)} clearly labeled fictional jobs")
        elif args.command == "import":
            batch = read_json(args.file)
            validate_batch(batch, config)
            import hashlib
            digest = hashlib.sha256(json.dumps(batch, sort_keys=True).encode()).hexdigest()[:16]
            target = ROOT / "data/inbox" / f"{batch['source_id']}-{digest}.json"
            write_json(target, batch)
            print(f"Validated local inbox: {target}")
        return 0
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
