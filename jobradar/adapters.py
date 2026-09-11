"""Public source adapters. All network traffic stays outside the static browser."""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

from .core import safe_url, plain, stamp


class Records(list):
    """A list with coverage information for a deliberately bounded crawl."""
    def __init__(self, rows=(), *, truncated=False):
        super().__init__(rows)
        self.truncated = truncated


def public_address(url):
    safe_url(url)
    for info in socket.getaddrinfo(urlsplit(url).hostname, None, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("来源域名解析到非公开地址")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_address(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    def __init__(self, rules):
        self.rules = rules
        self.opener = urllib.request.build_opener(SafeRedirect())
        self.last_request = 0

    def __call__(self, url):
        public_address(url)
        for attempt in range(self.rules["retries"] + 1):
            time.sleep(max(0, self.rules["request_delay_seconds"] - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "JobRadar/1.0 (public job aggregation)", "Accept": "application/json, application/xml, text/html, */*"})
                with self.opener.open(req, timeout=self.rules["timeout_seconds"]) as response:
                    body = response.read(5_000_001)
                    if len(body) > 5_000_000:
                        raise ValueError("响应超过 5 MB 上限")
                    return body.decode(response.headers.get_content_charset() or "utf-8")
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == self.rules["retries"]:
                    raise
                time.sleep(min(30, 2 ** attempt))
            except (urllib.error.URLError, TimeoutError):
                if attempt == self.rules["retries"]:
                    raise
                time.sleep(min(30, 2 ** attempt))


def greenhouse(source, rules, fetch):
    payload = json.loads(fetch(f"https://boards-api.greenhouse.io/v1/boards/{quote(source['board'])}/jobs?content=true"))
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("Greenhouse 返回结构无效")
    return [{"title": j["title"], "url": j["absolute_url"], "location": (j.get("location") or {}).get("name"), "description": j.get("content"), "updated_at": j.get("updated_at"), "tags": [d["name"] for d in j.get("departments", [])]} for j in payload["jobs"]]


def lever(source, rules, fetch):
    result = []
    host = "api.eu.lever.co" if source.get("region") == "eu" else "api.lever.co"
    for page in range(rules["max_pages"]):
        rows = json.loads(fetch(f"https://{host}/v0/postings/{quote(source['board'])}?mode=json&skip={page * 100}&limit=100"))
        if not isinstance(rows, list):
            raise ValueError("Lever 返回结构无效")
        for j in rows:
            c = j.get("categories") or {}
            description = " ".join([j.get("descriptionPlain") or j.get("description") or ""] + [plain(x.get("content")) for x in j.get("lists", [])] + [j.get("additionalPlain") or ""])
            salary = j.get("salaryRange") or {}
            salary_text = f"{salary.get('currency', '')} {salary.get('min', '')}–{salary.get('max', '')} / {salary.get('interval', '')}".strip() if salary else ""
            result.append({"title": j["text"], "url": j["hostedUrl"], "location": c.get("location"), "employment_type": c.get("commitment"), "workplace": "onsite" if j.get("workplaceType") == "on-site" else j.get("workplaceType"), "description": description, "salary": salary_text, "tags": [v for v in [c.get("team"), c.get("department")] if v]})
        if len(rows) < 100:
            break
    return result


def tencent(source, rules, fetch):
    """Read Tencent's public careers listing, newest-first, without login."""
    result = Records()
    seen = set()
    page_size = 50
    total = 0
    for page in range(1, rules["max_pages"] + 1):
        payload = json.loads(fetch(f"https://careers.tencent.com/tencentcareer/api/post/Query?pageIndex={page}&pageSize={page_size}&language=zh-cn"))
        data = payload.get("Data") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("Code") != 200 or not isinstance(data, dict) or not isinstance(data.get("Posts"), list) or not isinstance(data.get("Count"), int):
            raise ValueError("腾讯官网招聘接口格式变化或返回错误")
        total = data["Count"]
        rows = data["Posts"]
        if not rows:
            break
        new = 0
        for row in rows:
            post_id = str(row.get("PostId", ""))
            if not post_id.isdigit():
                raise ValueError("腾讯职位缺少有效 PostId")
            if post_id in seen:
                continue
            seen.add(post_id)
            new += 1
            if row.get("IsValid") is False:
                continue
            updated = row.get("LastUpdateTime", "")
            match = re.fullmatch(r"(\d{4})年(\d{2})月(\d{2})日", updated)
            updated_at = "-".join(match.groups()) + "T00:00:00+08:00" if match else None
            result.append({"title": row.get("RecruitPostName"), "company": "腾讯", "url": f"https://careers.tencent.com/jobdesc.html?postId={post_id}", "location": " · ".join(filter(None, [row.get("CountryName"), row.get("LocationName")])), "description": row.get("Responsibility"), "updated_at": updated_at, "tags": [v for v in [row.get("CategoryName"), row.get("BGName"), row.get("RequireWorkYearsName")] if v]})
        if len(seen) >= total or len(rows) < page_size:
            break
        if not new:
            result.truncated = True
            break
    result.truncated = result.truncated or len(seen) < total
    return result


def remotive(source, rules, fetch):
    """Free public remote-job API; keep Remotive's attribution URL."""
    payload = json.loads(fetch("https://remotive.com/api/remote-jobs"))
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("Remotive 返回结构无效")
    return [{"title": j["title"], "company": j.get("company_name"), "url": j["url"], "location": j.get("candidate_required_location") or "地区限制未注明", "workplace": "remote", "employment_type": j.get("job_type"), "salary": j.get("salary"), "description": j.get("description"), "tags": j.get("tags") or [], "published_at": j.get("publication_date")} for j in payload["jobs"]]


def rss(source, rules, fetch):
    body = fetch(source["url"])
    if "<!DOCTYPE" in body.upper() or "<!ENTITY" in body.upper():
        raise ValueError("不支持 XML DTD 或外部实体")
    root = ET.fromstring(body)
    atom = "{http://www.w3.org/2005/Atom}"
    if root.tag not in {"rss", atom + "feed"}:
        raise ValueError("响应不是受支持的 RSS 2.0 或 Atom feed")
    rows = root.findall(".//item") or root.findall(atom + "entry")
    result = []
    for row in rows:
        def content(*keys):
            for key in keys:
                el = row.find(key)
                if el is not None:
                    return "".join(el.itertext())
            return None
        link = content("link")
        if not link:
            link = next((el.get("href") for el in row.findall(atom + "link") if el.get("rel", "alternate") == "alternate"), None)
        published = content("pubDate", atom + "published")
        if published and row.tag != atom + "entry":
            published = stamp(parsedate_to_datetime(published))
        result.append({"title": content("title", atom + "title"), "url": link, "description": content("description", atom + "summary", atom + "content"), "published_at": published, "updated_at": content(atom + "updated"), "tags": [e.text for e in row.findall("category") if e.text]})
    return result


class JsonLDParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.chunks = []
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.inside = True
            self.current = []

    def handle_data(self, data):
        if self.inside:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.inside:
            self.chunks.append("".join(self.current))
            self.inside = False


def jsonld(source, rules, fetch):
    result = []
    def walk(value):
        if isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, dict):
            kind = value.get("@type", [])
            if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
                yield value
            for key in ("@graph", "itemListElement", "item"):
                if key in value:
                    yield from walk(value[key])
    for url in source["urls"][:rules["max_pages"]]:
        parser = JsonLDParser()
        parser.feed(fetch(url))
        for chunk in parser.chunks:
            for j in walk(json.loads(chunk)):
                locations = j.get("jobLocation", [])
                if isinstance(locations, dict):
                    locations = [locations]
                locs = []
                for loc in locations:
                    address = loc.get("address", {})
                    if isinstance(address, str):
                        locs.append(address)
                    else:
                        locs.append(" / ".join(str(address[k]) for k in ("addressLocality", "addressRegion", "addressCountry") if address.get(k)))
                remote = j.get("jobLocationType") == "TELECOMMUTE"
                salary = j.get("baseSalary") or {}
                value = salary.get("value", {}) if isinstance(salary, dict) else {}
                salary_text = ""
                if isinstance(value, dict) and (value.get("value") is not None or value.get("minValue") is not None):
                    amount = str(value["value"]) if value.get("value") is not None else f"{value.get('minValue', '')}–{value.get('maxValue', '')}"
                    salary_text = f"{salary.get('currency', '')} {amount} / {value.get('unitText', '')}".strip()
                employment = j.get("employmentType", "")
                result.append({"title": j.get("title"), "url": j.get("url") or url, "company": (j.get("hiringOrganization") or {}).get("name"), "description": j.get("description"), "location": " / ".join(locs) or ("远程" if remote else ""), "workplace": "remote" if remote else "unknown", "employment_type": ", ".join(employment) if isinstance(employment, list) else employment, "salary": salary_text, "published_at": j.get("datePosted"), "expires_at": j.get("validThrough")})
    if not result:
        raise ValueError("页面中未找到 JobPosting JSON-LD；请填写具体职位页")
    return result


ADAPTER_FUNCTIONS = {"greenhouse": greenhouse, "lever": lever, "rss": rss, "jsonld": jsonld, "tencent": tencent, "remotive": remotive}
