"""Validation, strategy resolution, normalization and lifecycle management."""
from __future__ import annotations

import copy
import hashlib
import html
import ipaddress
import json
import re
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {"greenhouse", "lever", "rss", "jsonld", "codex", "tencent", "remotive"}
SEARCH_KEYS = {"keywords", "exclude_keywords", "locations"}
STRATEGY_KEYS = SEARCH_KEYS | {"keyword_mode", "search_fields", "max_age_days", "stale_after_days", "max_results", "timeout_seconds", "request_delay_seconds", "retries", "max_pages", "min_interval_hours"}
FIELDS = {"title", "company", "location", "tags", "description"}


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value=None):
    return (value or utcnow()).isoformat(timespec="seconds").replace("+00:00", "Z")


def date(value):
    if not value:
        return None
    if not isinstance(value, str):
        raise ValueError("日期必须为 ISO 8601 字符串")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=result.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"无效日期: {value}") from exc


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value, limit=12000):
    parser = TextParser()
    parser.feed(html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()[:limit]


def safe_url(value):
    if not isinstance(value, str) or re.search(r"[\s\x00-\x1f\\]", value):
        raise ValueError("URL 不得包含空白、控制字符或反斜杠")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("仅允许不含凭据的公开 HTTP(S) URL")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".localhost", ".internal")) or "." not in host and ":" not in host:
        raise ValueError("不允许内部地址")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("不允许非公开 IP 地址")
    except ValueError as exc:
        if "不允许" in str(exc):
            raise
        if re.fullmatch(r"[0-9.]+", host) or re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host):
            raise ValueError("不允许非常规 IP 地址写法") from exc
    if parsed.port and parsed.port not in {80, 443}:
        raise ValueError("仅允许 80/443 端口")
    return value


def canonical_url(value):
    p = urlsplit(safe_url(value))
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def string_list(value, label):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{label} 必须是非空字符串组成的数组（允许空数组）")


def check_strategy(value, label):
    if not isinstance(value, dict) or set(value) - STRATEGY_KEYS:
        raise ValueError(f"{label} 包含未知策略字段")
    for key in SEARCH_KEYS & value.keys():
        string_list(value[key], key)
    if "keyword_mode" in value and value["keyword_mode"] not in {"any", "all"}:
        raise ValueError("keyword_mode 只能为 any 或 all")
    if "search_fields" in value:
        string_list(value["search_fields"], "search_fields")
        if not value["search_fields"] or set(value["search_fields"]) - FIELDS:
            raise ValueError("search_fields 包含未知字段或为空")
    bounds = {"max_age_days": (1, 3650), "stale_after_days": (1, 365), "max_results": (1, 1000), "timeout_seconds": (1, 120), "request_delay_seconds": (0, 60), "retries": (0, 5), "max_pages": (1, 20), "min_interval_hours": (0, 168)}
    for key, (low, high) in bounds.items():
        if key in value:
            v = value[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not low <= v <= high or (key != "request_delay_seconds" and not isinstance(v, int)):
                raise ValueError(f"{key} 必须介于 {low} 和 {high} 之间" + ("的整数" if key != "request_delay_seconds" else ""))


def validate_config(config):
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("配置 schema_version 必须为 1")
    if set(config) != {"schema_version", "project", "search", "defaults", "sources"}:
        raise ValueError("配置顶层字段必须是 schema_version/project/search/defaults/sources")
    if not isinstance(config["project"], dict) or set(config["project"]) != {"name", "description"} or any(not isinstance(v, str) for v in config["project"].values()) or not config["project"]["name"].strip():
        raise ValueError("project 需要 name 和 description 字符串")
    if not isinstance(config["search"], dict) or set(config["search"]) != SEARCH_KEYS:
        raise ValueError("search 需要 keywords/exclude_keywords/locations")
    check_strategy(config["search"], "search")
    required_defaults = STRATEGY_KEYS - SEARCH_KEYS - {"min_interval_hours"}
    if not isinstance(config["defaults"], dict) or not required_defaults <= config["defaults"].keys() or config["defaults"].keys() - (STRATEGY_KEYS - SEARCH_KEYS):
        raise ValueError("defaults 缺少或包含未知策略字段")
    check_strategy(config["defaults"], "defaults")
    if not isinstance(config["sources"], list):
        raise ValueError("sources 必须为数组")
    ids = set()
    allowed = {"id", "name", "adapter", "enabled", "board", "company", "region", "url", "urls", "query_template", "strategy", "notes"}
    for s in config["sources"]:
        if not isinstance(s, dict) or set(s) - allowed:
            raise ValueError("来源包含未知字段；不要将密钥写入配置")
        if not isinstance(s.get("id"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", s["id"]) or s["id"] in ids:
            raise ValueError("来源 id 必须唯一且只含小写字母、数字、连字符")
        ids.add(s["id"])
        if not isinstance(s.get("name"), str) or not s["name"].strip() or not isinstance(s.get("enabled"), bool) or s.get("adapter") not in ADAPTERS:
            raise ValueError(f"来源 {s['id']} 名称、启用状态或适配器无效")
        check_strategy(s.get("strategy", {}), s["id"])
        for k in {"company", "notes", "query_template"} & s.keys():
            if not isinstance(s[k], str):
                raise ValueError(f"{k} 必须为字符串")
        if s["adapter"] in {"greenhouse", "lever"} and (not isinstance(s.get("board"), str) or not re.fullmatch(r"[\w-]+", s["board"], re.ASCII)):
            raise ValueError("board 必须为招聘板标识")
        if s.get("region", "global") not in {"global", "eu"}:
            raise ValueError("region 必须是 global 或 eu")
        if "url" in s:
            safe_url(s["url"])
        if s["adapter"] in {"rss", "codex"} and not s.get("url"):
            raise ValueError("RSS/Codex 来源需要 url")
        if "urls" in s:
            string_list(s["urls"], "urls")
            for url in s["urls"]:
                safe_url(url)
        if s["adapter"] == "jsonld" and not s.get("urls"):
            raise ValueError("JSON-LD 来源需要 urls")
    return config


def load_config(path=None):
    return validate_config(json.loads(Path(path or ROOT / "config/search.json").read_text(encoding="utf-8-sig")))


def strategy(config, source):
    # Lists replace lists, including an explicit [] to clear global filtering.
    return {"min_interval_hours": 0, **copy.deepcopy(config["defaults"]), **copy.deepcopy(config["search"]), **copy.deepcopy(source.get("strategy", {}))}


def normalize(raw, source, now=None):
    now = now or utcnow()
    if not isinstance(raw, dict):
        raise ValueError("岗位必须为对象")
    for k in ("title", "url"):
        if not isinstance(raw.get(k), str) or not raw[k].strip():
            raise ValueError(f"岗位缺少 {k}")
    url = canonical_url(raw["url"])
    tags = raw.get("tags", [])
    string_list(tags, "tags")
    published = date(raw.get("published_at"))
    updated = date(raw.get("updated_at"))
    expiry = date(raw.get("expires_at"))
    if published and published > now + timedelta(days=1):
        raise ValueError("发布日期不能晚于当前时间")
    record = {
        "id": hashlib.sha256(url.encode()).hexdigest()[:20], "title": plain(raw["title"], 300),
        "company": plain(raw.get("company") or source.get("company") or "未注明公司", 200),
        "location": plain(raw.get("location") or "未注明地点", 200),
        "workplace": raw.get("workplace") if raw.get("workplace") in {"remote", "hybrid", "onsite"} else "unknown",
        "employment_type": plain(raw.get("employment_type"), 100), "salary": plain(raw.get("salary"), 200),
        "url": url, "description": plain(raw.get("description")), "tags": list(dict.fromkeys(plain(t, 80) for t in tags)),
        "published_at": stamp(published) if published else None, "updated_at": stamp(updated) if updated else None,
        "expires_at": stamp(expiry) if expiry else None, "first_seen_at": stamp(now), "last_seen_at": stamp(now),
        "source_id": source["id"], "source_name": source["name"], "source_ids": [source["id"]],
        "status": "active", "demo": bool(raw.get("demo", False)),
        "evidence_url": canonical_url(raw.get("evidence_url") or url),
    }
    if not record["title"]:
        raise ValueError("岗位标题为空")
    return record


def matches(job, rules, now=None):
    now = now or utcnow()
    text = " ".join(" ".join(job.get(k, [])) if isinstance(job.get(k), list) else str(job.get(k) or "") for k in rules["search_fields"]).casefold()
    keywords = [k.casefold() for k in rules["keywords"]]
    if keywords and not (all(k in text for k in keywords) if rules["keyword_mode"] == "all" else any(k in text for k in keywords)):
        return False
    if any(k.casefold() in text for k in rules["exclude_keywords"]):
        return False
    if rules["locations"] and not any(k.casefold() in job["location"].casefold() for k in rules["locations"]):
        return False
    published = date(job.get("published_at"))
    return not published or (now - published).total_seconds() <= rules["max_age_days"] * 86400


def merge_jobs(previous, incoming, config, now=None):
    now = now or utcnow()
    sources = {s["id"]: s for s in config["sources"] if s["enabled"]}
    merged = {}
    # Remove demo records on a real run; keep prior real records through failures.
    for job in previous:
        remaining = sorted(set(job.get("source_ids", [job.get("source_id")])) & sources.keys())
        if not job.get("demo") and remaining:
            retained = copy.deepcopy(job)
            retained["source_ids"] = remaining
            if retained["source_id"] not in sources:
                retained["source_id"] = remaining[0]
                retained["source_name"] = sources[remaining[0]]["name"]
            merged[job["id"]] = retained
    for job in incoming:
        old = merged.get(job["id"])
        if old:
            primary = old if date(old["last_seen_at"]) > date(job["last_seen_at"]) else job
            job = {**primary, "first_seen_at": stamp(min(date(old["first_seen_at"]), date(job["first_seen_at"]))), "source_ids": sorted(set(old.get("source_ids", [old["source_id"]])) | set(job["source_ids"]))}
        merged[job["id"]] = job
    result = []
    for job in merged.values():
        s = sources.get(job["source_id"])
        if not s:
            continue
        matching_sources = [sources[sid] for sid in job["source_ids"] if sid in sources and matches(job, strategy(config, sources[sid]), now)]
        if not matching_sources:
            continue
        if s not in matching_sources:
            s = matching_sources[0]
            job["source_id"], job["source_name"] = s["id"], s["name"]
        rules = strategy(config, s)
        expired = date(job.get("expires_at"))
        stale = now - date(job["last_seen_at"]) > timedelta(days=rules["stale_after_days"])
        job["status"] = "expired" if expired and expired < now else "stale" if stale else "active"
        result.append(job)
    return sorted(result, key=lambda j: (j.get("published_at") or j["first_seen_at"], j["id"]), reverse=True)


def read_json(path, fallback=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else fallback


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
