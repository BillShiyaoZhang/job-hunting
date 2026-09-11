"""Ensure that only intentional static assets are ready for publishing."""
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1] / "dist"
allowed = {"index.html", "styles.css", "app.mjs", "lib.mjs", "favicon.svg", ".nojekyll", "data/jobs.json", "data/config.json", "data/runs.json"}
actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
if actual != allowed:
    raise SystemExit(f"Static file mismatch; missing={allowed - actual}; unexpected={actual - allowed}")


class Check(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for k in ("href", "src"):
            ref = attrs.get(k, "")
            if not ref or ref.startswith("#") or urlsplit(ref).scheme:
                continue
            if ref.startswith("/"):
                raise ValueError(f"Asset must support GitHub Pages subpaths: {ref}")
            if not (root / ref).is_file():
                raise ValueError(f"Missing local asset: {ref}")


Check().feed((root / "index.html").read_text(encoding="utf-8"))
for name in ("jobs", "config", "runs"):
    json.loads((root / f"data/{name}.json").read_text(encoding="utf-8"))
print(f"OK: {len(actual)} public files, all local references resolve, subpath-safe entrypoint")
