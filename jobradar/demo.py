"""Fictional, labeled content for offline acceptance. Never a live fallback."""
from datetime import timedelta
from .core import ROOT, normalize, read_json, stamp, utcnow, write_json


def create_demo(config, force=False):
    old = read_json(ROOT / "data/jobs.json", {})
    if old and not old.get("demo") and not force:
        raise ValueError("已有正式数据；demo 默认不会覆盖。确认需要替换时使用 --force。")
    now = utcnow()
    rows = [
        ("高级前端工程师", "云岫科技", "上海 · 徐汇区", "hybrid", "30–45K · 16 薪", ["React", "TypeScript", "3–5 年"], "boss"),
        ("AI 产品经理", "星序智能", "北京 · 海淀区", "onsite", "35–50K · 15 薪", ["AI", "产品策略", "3–5 年"], "liepin"),
        ("Frontend Engineer", "Orbit Studio", "远程 · 亚太地区", "remote", "$90k–130k / 年", ["React", "Design System", "英语"], "lever"),
        ("Python 后端工程师", "山海数据", "杭州 · 余杭区", "hybrid", "25–40K · 14 薪", ["Python", "FastAPI", "3–5 年"], "greenhouse"),
        ("Product Designer", "Forma Labs", "远程 · 全球", "remote", "", ["Product", "Figma", "2–4 年"], "remote-rss"),
        ("AI 应用开发工程师", "萤石研究室", "深圳 · 南山区", "onsite", "30–55K · 16 薪", ["AI", "Python", "LLM"], "company-careers"),
        ("前端开发工程师", "青屿数字", "成都 · 高新区", "onsite", "18–28K · 14 薪", ["Vue", "TypeScript", "1–3 年"], "boss"),
        ("Senior Platform Engineer", "Northstar Systems", "远程 · 欧洲", "remote", "€80k–110k / 年", ["Python", "Kubernetes", "5 年以上"], "greenhouse"),
        ("数据产品经理", "知更科技", "上海 · 浦东新区", "hybrid", "28–42K · 15 薪", ["Product", "数据分析", "3–5 年"], "liepin"),
        ("Full Stack Engineer", "Morrow Works", "新加坡", "hybrid", "", ["React", "Node.js", "3–5 年"], "lever"),
        ("机器学习工程师", "远川智能", "北京 · 朝阳区", "onsite", "35–60K · 16 薪", ["AI", "Python", "PyTorch"], "company-careers"),
        ("React Native Engineer", "Tidal Apps", "远程 · 全球", "remote", "$70k–100k / 年", ["React", "Mobile", "2–4 年"], "remote-rss")
    ]
    jobs = []
    for i, (title, company, location, workplace, salary, tags, source_id) in enumerate(rows):
        source = next((s for s in config["sources"] if s["id"] == source_id), config["sources"][i % len(config["sources"])] if config["sources"] else {"id": "demo", "name": "演示来源"})
        raw = {"title": title, "company": company, "location": location, "workplace": workplace, "salary": salary, "tags": tags, "employment_type": "全职", "url": f"https://example.com/jobs/demo-{i+1}", "published_at": stamp(now - timedelta(days=i // 2)), "demo": True, "description": f"这是用于功能预览的虚构岗位，不代表 {source['name']} 上的真实招聘信息。参与{tags[0]}相关产品的设计与建设，与产品、设计和研发团队协作，关注用户体验和交付质量。所有公司、薪资和岗位信息均为示例。"}
        jobs.append(normalize(raw, source, now - timedelta(hours=i)))
    dataset = {"schema_version": 1, "generated_at": stamp(now), "demo": True, "jobs": jobs}
    write_json(ROOT / "data/jobs.json", dataset)
    run = {"schema_version": 1, "started_at": stamp(now), "finished_at": stamp(now), "mode": "demo", "status": "demo", "total_jobs": len(jobs), "sources": [{"source_id": s["id"], "name": s["name"], "adapter": s["adapter"], "status": "disabled", "found": 0, "accepted": 0, "coverage": "partial", "message": "未执行真实采集"} for s in config["sources"]]}
    write_json(ROOT / "data/runs/latest.json", run)
    write_json(ROOT / "data/runs/history.json", [run])
