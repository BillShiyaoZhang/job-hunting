"""CLI orchestration, inbox contract and deterministic static publishing."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

from .adapters import ADAPTER_FUNCTIONS, Fetcher
from .core import ROOT, date, load_config, matches, merge_jobs, normalize, read_json, stamp, strategy, utcnow, write_json


def validate_batch(batch, config, now=None):
    now = now or utcnow()
    if not isinstance(batch, dict) or batch.get("schema_version") != 1:
        raise ValueError("inbox schema_version 必须为 1")
    if set(batch) - {"schema_version", "source_id", "collected_at", "status", "coverage", "message", "jobs"}:
        raise ValueError("inbox 包含未知字段")
    source = next((s for s in config["sources"] if s["id"] == batch.get("source_id") and s["adapter"] == "codex"), None)
    if not source:
        raise ValueError("inbox source_id 必须指向已配置的 Codex 来源")
    observed = date(batch.get("collected_at"))
    if not observed or observed > now + timedelta(minutes=5):
        raise ValueError("inbox collected_at 必须是真实观察时间，不能位于未来")
    if batch.get("status") not in {"ok", "blocked", "error"} or batch.get("coverage") != "partial":
        raise ValueError("inbox status 必须为 ok/blocked/error，coverage 必须为 partial")
    if not isinstance(batch.get("message", ""), str):
        raise ValueError("inbox message 必须是字符串")
    jobs = batch.get("jobs")
    if not isinstance(jobs, list) or len(jobs) > 1000 or batch["status"] != "ok" and jobs:
        raise ValueError("inbox jobs 必须为至多 1000 条的数组，非 ok 批次必须为空")
    from urllib.parse import urlsplit
    domain = urlsplit(source["url"]).hostname.removeprefix("www.")
    normalized = []
    for raw in jobs:
        if raw.get("demo"):
            raise ValueError("正式 inbox 不接受演示岗位")
        if not raw.get("evidence_url"):
            raise ValueError("inbox 岗位必须包含 evidence_url，且应为已核实的职位原文")
        job = normalize(raw, source, observed)
        for key in ("url", "evidence_url"):
            host = urlsplit(job[key]).hostname.removeprefix("www.")
            if host != domain and not host.endswith("." + domain):
                raise ValueError(f"inbox {key} 不属于来源域名 {domain}")
        normalized.append(job)
    return source, normalized


def load_batches(config, inbox, now=None):
    batches = []
    for path in sorted(Path(inbox).glob("*.json")):
        if path.name == "example.json" or path.name.endswith(".local.json"):
            continue
        batch = read_json(path)
        try:
            source, jobs = validate_batch(batch, config, now)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        batches.append((batch, source, jobs))
    return sorted(batches, key=lambda b: date(b[0]["collected_at"]))


def validate_dataset(dataset):
    if not isinstance(dataset, dict) or dataset.get("schema_version") != 1 or not isinstance(dataset.get("jobs"), list) or not isinstance(dataset.get("demo"), bool) or not date(dataset.get("generated_at")):
        raise ValueError("岗位数据集结构无效")
    ids = set()
    for job in dataset["jobs"]:
        required = {"id", "title", "company", "url", "location", "description", "tags", "source_id", "source_name", "source_ids", "status", "demo", "first_seen_at", "last_seen_at", "workplace", "evidence_url"}
        if not isinstance(job, dict) or required - job.keys():
            raise ValueError("岗位数据缺少必要字段")
        normalized = normalize(job, {"id": job["source_id"], "name": job["source_name"]})
        if job["id"] != normalized["id"] or job["id"] in ids:
            raise ValueError("岗位 id 不匹配规范化 URL 或存在重复")
        ids.add(job["id"])
        if job["status"] not in {"active", "stale", "expired"} or not isinstance(job["demo"], bool):
            raise ValueError("岗位状态无效")
        if job["demo"] != dataset["demo"]:
            raise ValueError("不允许混合示例与正式岗位")
        if not date(job["first_seen_at"]) or not date(job["last_seen_at"]) or date(job["first_seen_at"]) > date(job["last_seen_at"]):
            raise ValueError("岗位观察时间无效")
    return dataset


def collect(config, data_dir=None, inbox=None, fetch_factory=Fetcher, now=None):
    now = now or utcnow()
    data_dir = Path(data_dir or ROOT / "data")
    enabled = [s for s in config["sources"] if s["enabled"]]
    if not enabled:
        raise ValueError("尚未启用任何来源。请先编辑 config/search.json；预览使用 demo 命令。")
    batches = load_batches(config, inbox or data_dir / "inbox", now)
    previous = read_json(data_dir / "jobs.json", {"jobs": []})
    if previous.get("jobs"):
        validate_dataset(previous)
    history = read_json(data_dir / "runs/history.json", [])
    incoming, outcomes = [], []
    for source in config["sources"]:
        outcome = {"source_id": source["id"], "name": source["name"], "adapter": source["adapter"], "status": "disabled", "found": 0, "accepted": 0, "message": "未启用", "coverage": "partial"}
        outcomes.append(outcome)
        if not source["enabled"]:
            continue
        rules = strategy(config, source)
        fingerprint = hashlib.sha256(json.dumps({"source": source, "strategy": rules}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
        outcome["config_fingerprint"] = fingerprint
        try:
            if source["adapter"] != "codex" and rules["min_interval_hours"] and previous.get("demo") is False:
                cached = next((o for r in history for o in r.get("sources", []) if o.get("source_id") == source["id"]), None)
                if cached and cached.get("config_fingerprint") == fingerprint and cached.get("status") in {"ok", "partial", "cached"} and cached.get("observed_at") and timedelta(0) <= now - date(cached["observed_at"]) < timedelta(hours=rules["min_interval_hours"]):
                    outcome.update(status="cached", found=cached["found"], accepted=cached["accepted"], observed_at=cached["observed_at"], message=f"沿用近期结果；最低抓取间隔 {rules['min_interval_hours']} 小时，保留原核验时间")
                    continue
            if source["adapter"] == "codex":
                relevant = [b for b in batches if b[1]["id"] == source["id"]]
                if not relevant:
                    outcome.update(status="pending", message="等待 Codex 核验批次")
                    continue
                latest = relevant[-1][0]
                outcome.update(status=latest["status"], message=latest.get("message", "Codex 批次已导入"), observed_at=latest["collected_at"])
                jobs = [job for b in relevant for job in b[2]]
                if now - date(latest["collected_at"]) > timedelta(days=rules["stale_after_days"]):
                    outcome.update(status="stale", message="最近的 Codex 批次已超过复核期限")
            else:
                rows = ADAPTER_FUNCTIONS[source["adapter"]](source, rules, fetch_factory(rules))
                jobs = []
                errors = 0
                for row in rows:
                    try:
                        jobs.append(normalize(row, source, now))
                    except (ValueError, TypeError, KeyError, AttributeError):
                        errors += 1
                if rows and not jobs:
                    raise ValueError("所有岗位均未通过字段校验")
                bounded = getattr(rows, "truncated", False) or source["adapter"] == "lever" and len(rows) >= rules["max_pages"] * 100 or source["adapter"] == "jsonld" and len(source["urls"]) > rules["max_pages"]
                outcome.update(status="partial" if errors or bounded else "ok", message=f"已读取 {len(rows)} 条；无效 {errors} 条" + ("；达到页数上限" if bounded else ""), observed_at=stamp(now))
            outcome["found"] = len(jobs)
            # Newest observations win and old inbox files cannot overwrite fresh facts.
            unique = {}
            for job in jobs:
                if matches(job, rules, now):
                    old = unique.get(job["id"])
                    if old:
                        winner = job if date(job["last_seen_at"]) >= date(old["last_seen_at"]) else old
                        unique[job["id"]] = {**winner, "first_seen_at": stamp(min(date(old["first_seen_at"]), date(job["first_seen_at"])))}
                    else:
                        unique[job["id"]] = job
            selected = sorted(unique.values(), key=lambda j: j["last_seen_at"], reverse=True)[:rules["max_results"]]
            if len(unique) > len(selected):
                outcome["message"] += "；达到结果上限"
                if outcome["status"] == "ok":
                    outcome["status"] = "partial"
            outcome["accepted"] = len(selected)
            incoming.extend(selected)
        except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            outcome.update(status="error", message=f"{type(exc).__name__}: {str(exc)[:300]}")
    jobs = merge_jobs(previous["jobs"], incoming, config, now)
    successful = any(o["status"] in {"ok", "partial", "cached"} for o in outcomes)
    trouble = any(o["status"] in {"error", "blocked", "pending", "stale", "partial"} for o in outcomes)
    run = {"schema_version": 1, "started_at": stamp(now), "finished_at": stamp(), "mode": "live", "status": "partial" if successful and trouble else "ok" if successful else "error", "total_jobs": len(jobs), "sources": outcomes}
    write_json(data_dir / "runs/latest.json", run)
    write_json(data_dir / "runs/history.json", ([run] + history)[:30])
    dataset = {"schema_version": 1, "generated_at": stamp(now), "demo": False, "jobs": jobs}
    validate_dataset(dataset)
    # Never replace an existing dataset with an empty failed collection.
    if successful or jobs:
        write_json(data_dir / "jobs.json", dataset)
    return run


def build(config, data_dir=None, output=None, production=False):
    data_dir = Path(data_dir or ROOT / "data")
    output = Path(output or ROOT / "dist")
    dataset = validate_dataset(read_json(data_dir / "jobs.json"))
    if production and dataset["demo"]:
        raise ValueError("发布构建拒绝示例数据；请先启用真实来源并 collect")
    if not (output / "index.html").is_file():
        raise ValueError("静态入口 index.html 不存在")
    write_json(output / "data/jobs.json", dataset)
    write_json(output / "data/config.json", config)
    write_json(output / "data/runs.json", read_json(data_dir / "runs/history.json", []))
    (output / ".nojekyll").touch()
    return len(dataset["jobs"])


def plan(config):
    plans = []
    for source in config["sources"]:
        if source["enabled"]:
            rules = strategy(config, source)
            template = source.get("query_template", "{keyword} {location}")
            queries = [template.replace("{keyword}", keyword).replace("{location}", location).strip() for keyword in rules["keywords"] or [""] for location in rules["locations"] or [""]]
            plans.append({"source_id": source["id"], "adapter": source["adapter"], "strategy": rules, "queries": queries if source["adapter"] == "codex" else [], "notes": source.get("notes", "")})
    return {"schema_version": 1, "sources": plans}
