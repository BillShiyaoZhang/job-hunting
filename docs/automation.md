# 工作雷达运行说明

## 当前运行状态

- 线上网页：https://billshiyaozhang.github.io/job-hunting/
- 源码仓库：`BillShiyaoZhang/job-hunting`，保持 private；仅 `dist/` 的静态网页和公开岗位数据发布到 Pages。
- 用户已明确授权启动运行、定时采集、Codex 核验与批次推送。
- GitHub Actions：每日北京时间 **09:37**（UTC 01:37）；inbox/config 推送也会触发刷新。
- Codex：每日北京时间 **09:10**，本任务 heartbeat，自动化 ID 记录在 `automation/task-preset.json`。
- 首轮真实运行：116 条岗位，腾讯 100、Flexport 7、Xsolla 5、Remotive 4。此数量仅代表首轮快照。
- BOSS/猎聘：当前原文核验受安全验证或旧缓存限制，记录为 blocked，不以搜索摘要充数。

## 免费范围

无需 API Key，没有购买、注册付费 API 或开启 OpenAI API 调用。腾讯、公司 ATS 和 Remotive 均使用免费公开数据。

启用前已在用户登录的 GitHub 页面确认现有免费 Pro 权益，以及账户级 Actions 额外预算 **$0 / Stop usage Yes**；这些限制没有提高。免费额度耗尽后可能停跑，不能为了继续运行自动升级或充值。源码私有不代表 Pages 网页私有；当前用户已明确授权公开静态网页。

[GitHub Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions) · [预算与停止使用](https://docs.github.com/en/billing/how-tos/set-up-budgets) · [Pages 支持条件](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)

## 数据与抓取策略

| 来源 | 免费读取方式 | 当前范围 |
| --- | --- | --- |
| 腾讯招聘 | 官网公开列表 API，标准库专用适配器 | 最新 4 页、最多 200 条原始记录；筛选大陆技术岗，最多入选 100 条 |
| Flexport | 官方 Greenhouse 招聘板 | 中国大陆匹配岗位 |
| Xsolla | 官方 Lever 招聘板 | 中国大陆匹配岗位 |
| Remotive | 免费公开远程 API | Worldwide/China/APAC/Asia，保留原始来源链接 |
| BOSS/猎聘 | Codex 原文核验 | 最多 3 页/来源，受阻则不导入岗位 |

默认公开来源最少间隔 12 小时再次抓取，Remotive 为 24 小时。冷却期间保留原核验时间；修改配置会使该来源缓存失效。Remotive 免费数据约延迟 24 小时，不承诺实时；用工地区限制仍需查看原文。[Remotive 使用说明](https://github.com/remotive-com/remote-jobs-api)

当前不需要 Scrapy/Playwright/付费爬虫平台代理。官网公开结构化接口比模拟登录更容易维护；已有 JSON-LD 适配器可读取配置的职位详情页，RSS/Atom 可接入明确允许的订阅源。动态或受限页面交由现有 Codex 浏览器核验；不绕过登录、验证码或访问限制。增加来源需先小样本实测，不能直接批量启用未经核验的 URL。

腾讯接口是官网当前页面接口，并非有长期稳定性承诺的开发者 API；结构变动时会报告失败、保留历史。采集分页/条数上限导致 partial 是明确的有限覆盖，不代表全部招聘帖已抓取。长时间未核验仅标为 stale；只有明确截止日已过才标 expired。

## GitHub 工作流

| 文件 | 职责 | 限制 |
| --- | --- | --- |
| `ci.yml` | push/PR/手动：离线校验、测试、构建 | 5 分钟超时，同一分支新 CI 取消旧 CI |
| `refresh.yml` | 采集、合并 inbox、构建、提交数据、部署本轮产物 | 默认分支，刷新 10 分钟，部署 5 分钟；报告保留 3 天 |
| `pages.yml` | 手动发布已保存的真实数据 | 默认分支，构建/部署各 5 分钟；拒绝示例数据 |

仓库 variables `ENABLE_JOB_REFRESH=true` 和 `ENABLE_PAGES_DEPLOY=true` 已开启。临时停采集可将前者设为 false；停发布将后者设为 false；不要删除源数据或提高预算。Codex 任务在 App 中单独暂停。

刷新在同一次 workflow 上传和发布当前产物，避免依赖 GITHUB_TOKEN 的机器人提交再次触发 push workflow。[GitHub token 行为](https://docs.github.com/en/actions/concepts/security/github_token)

来源失败或有限抓取不清空历史；所有来源均失败时工作流报错，不继续部署。失败附件包含本次阶段结果，不会将仓库里的旧采集报告冒充本次成功。部分来源成功时页面显示 partial 和逐源说明。默认分支保护或远程竞争导致推送失败时停止，不 force push。

## Codex 批次交接

完整协议在 `automation/codex-task.md`。任务先运行：

```bash
python -X utf8 scripts/sync_inbox.py --prepare
```

该脚本维护 `.local/codex-sync` 专用 checkout，使用已有 Git 认证并快进同步 main。它不会修改主工作区中用户的开发改动。Codex 读取专用副本的配置/数据，只处理启用的 codex 来源，将核验结果写到主项目 `.local/` 的唯一 JSON 文件。

```bash
python -X utf8 scripts/sync_inbox.py --batch .local/boss-本轮.json .local/liepin-本轮.json
```

脚本先校验全部输入，再在专用副本导入，只暂存本轮 inbox 文件并普通推送；格式校验失败不会写入部分批次，修正后可以重试。相同批次幂等，不产生新提交，已用现有真实受阻批次验证为 unchanged。脏副本、遗留锁、未推送提交或认证失败会明确停止，保留现场；不要自动删除、stash 或 force push。

批次协议：schema_version=1，source_id 指向 codex 来源，collected_at 使用真实 ISO 8601 观察时间，status=ok/blocked/error，coverage=partial，message 为简短说明，jobs 为数组。非 ok 批次 jobs 必须为空；单条岗位必须有 title/url/evidence_url，链接属于来源域名。未知字段事实留空，详情不包含登录凭据或无关个人信息。`data/inbox/example.json` 永远不参与导入。

Codex 本地任务需要电脑开机、App 运行及项目路径可用；关闭 App 或设备睡眠时不承诺执行。GitHub 的公开来源日更不依赖本机。定时任务沿用现有 Codex 账户额度，不是另购 API；预算/工具不可用时报告并停止。[OpenAI 定时任务说明](https://learn.chatgpt.com/docs/automations?surface=app)

## 修改配置与排错

- 网页配置是浏览器草稿：导出 search.json，替换仓库 `config/search.json`，校验并提交后才影响采集。
- 运行记录显示 cached：来源在最短抓取间隔内，复用近期结果，last_seen 不会假装刷新。
- 页面保留旧岗位：失败保留机制；查看 Actions 的本次附件和错误步骤。
- 本机采集提示“解析到非公开地址”：某些透明代理使用保留地址映射。当前由 GitHub runner 抓取，保持网络校验，不关闭校验或绕过安全代理设置。
- BOSS/猎聘 blocked：无需反复触发或购买破解服务，定时任务下一轮会低频重试可访问原文。
- 添加大型来源前，适当设置 max_pages/max_results/timeout 和 min_interval_hours，检查 Actions 的共享免费额度。
