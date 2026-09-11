import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from jobradar.core import canonical_url, load_config, matches, merge_jobs, normalize, plain, safe_url, stamp, strategy, validate_config, write_json, read_json
from jobradar.pipeline import build, collect, load_batches, validate_batch, validate_dataset
from jobradar.adapters import greenhouse, lever, rss, jsonld, tencent, remotive

NOW = datetime(2026, 9, 11, 10, tzinfo=timezone.utc)


def config():
    c = load_config(Path(__file__).parent / 'fixtures/search.json')
    c["search"] = {"keywords": [], "exclude_keywords": [], "locations": []}
    for s in c["sources"]:
        s["strategy"] = {}
        s["enabled"] = True
    return c


def job(source, now=NOW, **extra):
    return normalize({"title": "React Engineer", "url": "https://jobs.example.com/jobs/123", "description": "Build with React and Python", **extra}, source, now)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.c = config()
        self.s = self.c["sources"][0]

    def test_override_empty_lists_and_no_mutation(self):
        self.c["search"]["keywords"] = ["Python"]
        self.s["strategy"] = {"keywords": [], "retries": 0}
        rules = strategy(self.c, self.s)
        self.assertEqual(rules["keywords"], [])
        self.assertEqual(rules["retries"], 0)
        rules["search_fields"].append("company")
        self.assertNotIn("company", self.c["defaults"]["search_fields"])

    def test_all_exclusions_locations_and_age(self):
        rules = strategy(self.c, self.s)
        rules.update(keywords=["react", "python"], keyword_mode="all", locations=["上海"])
        j = job(self.s, location="上海 · 徐汇", published_at="2026-09-10T00:00:00Z")
        self.assertTrue(matches(j, rules, NOW))
        rules["exclude_keywords"] = ["Python"]
        self.assertFalse(matches(j, rules, NOW))
        rules["exclude_keywords"] = []
        j["published_at"] = "2025-01-01T00:00:00Z"
        self.assertFalse(matches(j, rules, NOW))
        j["published_at"] = None
        self.assertTrue(matches(j, rules, NOW))

    def test_no_false_cross_city_dedup(self):
        a = job(self.s, url="https://example.com/job?source=123")
        b = job(self.s, url="https://example.com/job?source=456")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(canonical_url(a["url"] + "&utm_source=site"), a["url"])

    def test_replay_keeps_new_facts_and_oldest_first_seen(self):
        old = job(self.s, NOW - timedelta(days=5), title="Old title")
        fresh = job(self.s, NOW, title="Fresh title")
        merged = merge_jobs([fresh], [old], self.c, NOW)[0]
        self.assertEqual(merged["title"], "Fresh title")
        self.assertEqual(merged["last_seen_at"], stamp(NOW))
        self.assertEqual(merged["first_seen_at"], stamp(NOW - timedelta(days=5)))

    def test_dedup_retains_enabled_provenance(self):
        other = self.c["sources"][1]
        merged = merge_jobs([], [job(self.s), job(other)], self.c, NOW)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]["source_ids"]), 2)
        other["enabled"] = False
        retained = merge_jobs(merged, [], self.c, NOW)
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]["source_id"], self.s["id"])

    def test_stale_is_not_expired(self):
        stale = job(self.s, NOW - timedelta(days=20))
        expired = job(self.s, url="https://example.com/other", expires_at="2026-09-10T00:00:00Z")
        result = merge_jobs([stale], [expired], self.c, NOW)
        self.assertEqual({j["status"] for j in result}, {"stale", "expired"})

    def test_unsafe_urls_and_html(self):
        for url in ["javascript:alert(1)", "http://localhost./a", "http://127.1/a", "http://10.1.1.1/a", "https://user:pass@example.com/a", "http://[::1]/", "https://example.com:8080/a", "https://example.com/\nx"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                safe_url(url)
        self.assertEqual(plain('<p>Hello</p><script>alert(1)</script><img onerror="bad">&amp; world'), "Hello & world")

    def test_bad_config_fails_closed(self):
        for mutate in [lambda c: c["defaults"].update(retries=True), lambda c: c["defaults"].update(max_results=1.5), lambda c: c["sources"][0].update(api_key="secret"), lambda c: c["sources"].append(copy.deepcopy(c["sources"][0]))]:
            c = config()
            mutate(c)
            with self.assertRaises(ValueError):
                validate_config(c)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.c = config()
        self.rules = strategy(self.c, self.c["sources"][0])

    def test_greenhouse_updated_date_is_not_published(self):
        payload = {"jobs": [{"id": 12, "title": "Engineer", "absolute_url": "https://example.com/job", "location": {"name": "London"}, "content": "&lt;p&gt;React&lt;/p&gt;", "updated_at": "2026-09-10T00:00:00Z", "departments": [{"name": "Engineering"}]}]}
        records = greenhouse(self.c["sources"][0], self.rules, lambda url: json.dumps(payload))
        self.assertNotIn("published_at", records[0])
        self.assertEqual(plain(records[0]["description"]), "React")

    def test_lever_pagination_and_workplace(self):
        calls = []
        row = {"text": "Engineer", "hostedUrl": "https://example.com/job", "categories": {"location": "上海"}, "workplaceType": "on-site"}
        def fetch(url):
            calls.append(url)
            return json.dumps([row] * (100 if len(calls) == 1 else 1))
        rows = lever(self.c["sources"][1], self.rules, fetch)
        self.assertEqual(len(rows), 101)
        self.assertIn("skip=100", calls[-1])
        self.assertEqual(rows[0]["workplace"], "onsite")

    def test_rss_atom_dates_and_link(self):
        source = self.c["sources"][2]
        xml = '<rss><channel><item><title>Engineer</title><link>https://example.com/1</link><pubDate>Thu, 10 Sep 2026 09:00:00 GMT</pubDate></item></channel></rss>'
        self.assertEqual(rss(source, self.rules, lambda _: xml)[0]["published_at"], "2026-09-10T09:00:00Z")
        atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Engineer</title><link rel="self" href="https://example.com/feed"/><link href="https://example.com/job"/><updated>2026-09-10T09:00:00Z</updated></entry></feed>'
        self.assertEqual(rss(source, self.rules, lambda _: atom)[0]["url"], "https://example.com/job")
        with self.assertRaises(ValueError):
            rss(source, self.rules, lambda _: '<!DOCTYPE rss><rss/>')
        with self.assertRaises(ValueError):
            rss(source, self.rules, lambda _: '<html><body>Login required</body></html>')

    def test_jsonld_graph_salary_and_remote(self):
        payload = {"@graph": [{"@type": "JobPosting", "title": "Engineer", "jobLocationType": "TELECOMMUTE", "datePosted": "2026-09-10", "hiringOrganization": {"name": "Test"}, "baseSalary": {"currency": "USD", "value": {"minValue": 90, "maxValue": 120, "unitText": "YEAR"}}}]}
        rows = jsonld(self.c["sources"][-1], self.rules, lambda _: '<script type="application/ld+json">' + json.dumps(payload) + '</script>')
        self.assertEqual(rows[0]["workplace"], "remote")
        self.assertIn("90–120", rows[0]["salary"])

    def test_tencent_boundaries_dates_and_official_links(self):
        rules = {**self.rules, 'max_pages': 1}
        payload = {'Code':200, 'Data':{'Count':1000, 'Posts':[{'PostId':'123', 'RecruitPostName':'后端开发工程师','CountryName':'中国','LocationName':'深圳','CategoryName':'技术','LastUpdateTime':'2026年09月10日','Responsibility':'Build services','IsValid':True}]}}
        rows = tencent({}, rules, lambda url: json.dumps(payload))
        self.assertTrue(rows.truncated)
        self.assertEqual(rows[0]['url'], 'https://careers.tencent.com/jobdesc.html?postId=123')
        self.assertEqual(rows[0]['updated_at'], '2026-09-10T00:00:00+08:00')
        self.assertNotIn('published_at', rows[0])
        with self.assertRaises(ValueError):
            tencent({}, rules, lambda url: '{"Code":403}')

    def test_remotive_preserves_attribution_and_location_restrictions(self):
        payload = {'jobs':[{'title':'Backend Engineer','company_name':'Acme','url':'https://remotive.com/remote-jobs/software-dev/engineer-123','candidate_required_location':'USA Only','publication_date':'2026-09-10T12:00:00','tags':['Python']}]}
        rows = remotive({}, self.rules, lambda url: json.dumps(payload))
        self.assertEqual(rows[0]['location'], 'USA Only')
        self.assertTrue(rows[0]['url'].startswith('https://remotive.com/'))
        self.assertEqual(rows[0]['workplace'], 'remote')
        record = normalize(rows[0], self.c['sources'][0], NOW)
        self.assertFalse(matches(record, {**self.rules,'locations':['Worldwide','China','APAC','Asia']}, NOW))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.c = config()
        self.boss = next(s for s in self.c["sources"] if s["id"] == "boss")

    def batch(self, **extra):
        return {"schema_version": 1, "source_id": "boss", "collected_at": stamp(NOW), "status": "ok", "coverage": "partial", "jobs": [{"title": "React Engineer", "url": "https://www.zhipin.com/job_detail/123", "evidence_url": "https://www.zhipin.com/job_detail/123"}], **extra}

    def test_inbox_domain_future_and_blocked_validation(self):
        validate_batch(self.batch(), self.c, NOW)
        for batch in [self.batch(collected_at=stamp(NOW + timedelta(days=1))), self.batch(status="blocked"), self.batch(jobs=[{"title":"Engineer", "url":"https://evil.example.com/1", "evidence_url":"https://evil.example.com/1"}])]:
            with self.assertRaises(ValueError):
                validate_batch(batch, self.c, NOW)

    def test_timezone_order_and_repeated_import_no_refresh(self):
        for s in self.c["sources"]:
            s["enabled"] = s["id"] == "boss"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'inbox/new.json', self.batch(collected_at='2026-09-11T05:00:00Z'))
            old = self.batch(collected_at='2026-09-11T12:00:00+08:00')
            old['jobs'][0]['title'] = 'Old job'
            write_json(root / 'inbox/old.json', old)
            batches = load_batches(self.c, root / 'inbox', NOW)
            self.assertEqual(batches[-1][0]['collected_at'], '2026-09-11T05:00:00Z')
            collect(self.c, root, now=NOW)
            collect(self.c, root, now=NOW + timedelta(days=1))
            jobs = read_json(root / 'jobs.json')['jobs']
            self.assertEqual(jobs[0]['title'], 'React Engineer')
            self.assertEqual(jobs[0]['last_seen_at'], '2026-09-11T05:00:00Z')

    def test_collection_failure_preserves_history(self):
        for s in self.c["sources"]:
            s["enabled"] = s["id"] == 'greenhouse'
        source = self.c['sources'][0]
        prior = job(source, NOW - timedelta(days=2))
        def factory(rules):
            def fail(url):
                raise OSError('Network unavailable')
            return fail
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'jobs.json', {'schema_version':1,'generated_at':stamp(NOW),'demo':False,'jobs':[prior]})
            run = collect(self.c, root, fetch_factory=factory, now=NOW)
            after = read_json(root / 'jobs.json')['jobs'][0]
            self.assertEqual(run['status'], 'error')
            self.assertEqual(after['last_seen_at'], prior['last_seen_at'])
            self.assertEqual(after['title'], prior['title'])

    def test_build_rejects_demo_for_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'index.html').write_text('hello')
            write_json(root / 'jobs.json', {'schema_version':1,'generated_at':stamp(NOW),'demo':True,'jobs':[job(self.c['sources'][0],demo=True)]})
            with self.assertRaises(ValueError):
                build(self.c, data_dir=root, output=root, production=True)
            self.assertEqual(build(self.c, data_dir=root, output=root), 1)

    def test_no_enabled_sources_cannot_destroy_demo(self):
        with self.assertRaises(ValueError):
            collect(load_config(Path(__file__).parent / 'fixtures/search.json'))

    def test_source_cooldown_preserves_observation_and_config_changes_invalidate(self):
        for s in self.c['sources']:
            s['enabled'] = s['id'] == 'greenhouse'
        self.c['defaults']['min_interval_hours'] = 24
        calls = []
        def factory(rules):
            def fetch(url):
                calls.append(url)
                return json.dumps({'jobs':[{'title':'React Engineer','absolute_url':'https://example.com/one'}]})
            return fetch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collect(self.c, root, fetch_factory=factory, now=NOW)
            run = collect(self.c, root, fetch_factory=factory, now=NOW + timedelta(hours=1))
            self.assertEqual(run['sources'][0]['status'], 'cached')
            self.assertEqual(len(calls), 1)
            self.assertEqual(read_json(root/'jobs.json')['jobs'][0]['last_seen_at'], stamp(NOW))
            self.c['search']['keywords'] = ['React']
            collect(self.c, root, fetch_factory=factory, now=NOW + timedelta(hours=2))
            self.assertEqual(len(calls), 2)
            self.c['search']['keywords'] = ['Python']
            collect(self.c, root, fetch_factory=factory, now=NOW + timedelta(hours=3))
            self.assertEqual(read_json(root/'jobs.json')['jobs'], [])
            self.c['search']['keywords'] = ['React']
            collect(self.c, root, fetch_factory=factory, now=NOW + timedelta(hours=4))
            self.assertEqual(len(calls), 4)
            self.assertEqual(len(read_json(root/'jobs.json')['jobs']), 1)

    def test_end_to_end_public_and_codex_to_static(self):
        for s in self.c['sources']:
            s['enabled'] = s['id'] in {'greenhouse', 'boss'}
        self.c['search']['keywords'] = ['React']
        self.c['search']['exclude_keywords'] = ['Outsource']
        payload = {'jobs': [
            {'title': 'React Engineer', 'absolute_url': 'https://example.com/api-job', 'location': {'name': 'Remote'}},
            {'title': 'React Outsource', 'absolute_url': 'https://example.com/excluded'}
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / 'dist'
            site.mkdir()
            (site / 'index.html').write_text('<!doctype html><title>Test site</title>')
            write_json(root / 'inbox/batch.json', self.batch())
            run = collect(self.c, root, fetch_factory=lambda rules: lambda url: json.dumps(payload), now=NOW)
            self.assertEqual(run['status'], 'ok')
            self.assertEqual(build(self.c, root, site, production=True), 2)
            result = read_json(site / 'data/jobs.json')
            validate_dataset(result)
            self.assertFalse(result['demo'])
            self.assertEqual({j['source_id'] for j in result['jobs']}, {'greenhouse', 'boss'})
            self.assertEqual(read_json(site / 'data/runs.json')[0]['total_jobs'], 2)


if __name__ == '__main__':
    unittest.main()
