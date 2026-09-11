# 检索配置与来源接入

配置文件为 `config/search.json`，UTF-8 JSON。CLI 和前端均校验字段和类型，CLI 是最终校验入口。

## 策略继承

每个来源的生效策略为：

```text
defaults + search + source.strategy
```

从左到右覆盖，所有字段是平面结构。数组整体替换，**不是追加**；`[]` 表示清空限制，未指定字段表示继承。显式的 `0`（允许的字段）不会被当成空值。

```json
{
  "id": "my-team",
  "name": "目标团队",
  "enabled": true,
  "adapter": "greenhouse",
  "board": "company-board-token",
  "company": "目标公司",
  "strategy": {
    "keywords": ["React", "TypeScript"],
    "keyword_mode": "all",
    "locations": ["Shanghai", "上海"],
    "max_results": 40
  }
}
```

`python -m jobradar plan` 会输出合并后的策略。关闭来源后，下一次成功采集会从正式数据集中移除仅属于该来源的岗位；多来源岗位仍有启用来源时保留。

## 字段说明

| 字段 | 含义 |
| --- | --- |
| `search.keywords` | 大小写不敏感的子串匹配，中英文均可；空数组不过滤 |
| `search.exclude_keywords` | 匹配任意排除词即排除；使用与关键词相同的检索字段 |
| `search.locations` | 任意地点词出现在 location 即匹配；空数组不限 |
| `keyword_mode` | `any` 任意关键词或 `all` 所有关键词；不使用正则 |
| `search_fields` | `title/company/location/tags/description`，至少一个 |
| `max_age_days` | 1–3650，只限制已知发布日期；未知日期不会伪造 |
| `stale_after_days` | 1–365，最近观察超过期限标记 `stale`（待复核） |
| `max_results` | 1–1000，每来源每次通过筛选后接受的最多唯一岗位数；不截断已持久保存的历史总数 |
| `timeout_seconds` | 1–120，每个 HTTP 请求的超时 |
| `request_delay_seconds` | 0–60，可为小数；同一来源请求之间的最低间隔 |
| `retries` | 0–5，暂时性网络错误、429 和部分 5xx 的重试次数 |
| `max_pages` | 1–20，Lever API 页数 / JSON-LD URL 数 / Codex 浏览页数上限；Greenhouse 和 RSS 为单次请求 |

除请求间隔外，数值字段必须是整数。未知字段会报错，以免拼写错误导致策略静默失效。

API 获取公开列表后在本地过滤；不能把这些关键词参数理解为所有第三方接口都支持服务端全文检索。BOSS、猎聘等 Codex 查询会展开 `query_template` 的 `{keyword}` 和 `{location}`，最终仍按完整策略复核。

## 可接入的来源

### Greenhouse

设置 `adapter: "greenhouse"`、`board` 和可选的 `company`。每家公司可以单独添加一个不同 ID 的来源。GET 列表接口不需要密钥；返回全量公开招聘帖，`content=true` 提供描述和部门。该接口没有已文档化的列表分页参数。`updated_at` 仅表示原文更新时间。[Greenhouse 官方 Job Board API](https://docs.greenhouse.io/job-board.html#list-jobs)

### Lever

设置 `adapter: "lever"`、`board`、`region: "global"` 或 `"eu"`。按每页 100 条使用 skip/limit 分页，遇到短页停止，达到配置上限会标记部分完成。记录工作方式和可用薪资范围；没有发布日期时保持未知。[Lever 官方 Postings API](https://github.com/lever/postings-api)

### RSS / Atom

设置 `adapter: "rss"` 与 `url`。RSS 读取 title/link/description/pubDate/category；Atom 读取 alternate link、summary/content、published 和 updated。没有统一分页或结构化薪资地点，不从描述中猜测这些字段，必要时用 `company` 提供已知发布方。

RSS 的 GUID 不一定是 URL；Atom 的 updated 不等于 published。本项目遵循这一区别。[RSS 规范](https://www.rssboard.org/rss-specification)、[Atom 规范](https://www.rfc-editor.org/rfc/rfc4287.html)

### JSON-LD 职位页

设置 `adapter: "jsonld"`，`urls` 填写具体职位原文地址。解析 `<script type="application/ld+json">` 中的 `JobPosting`，支持数组、`@graph` 和 ItemList 中的 item。读取职位、公司、工作地点、工作方式、薪资和日期。

这是**已知详情页读取器**，不会自动找到列表页中的所有职位，也不执行页面 JavaScript。需动态加载或需要发现新的详情页时，使用 Codex 来源。URL 数受 `max_pages` 限制。[Schema.org JobPosting](https://schema.org/JobPosting)

### Codex 浏览器检索

设置 `adapter: "codex"`、网站 `url` 和可选 `query_template`，在 `notes` 中写站点定制说明，例如“优先校招频道；只核验近两周发布的岗位”。其作用是指导定时任务，不会被 Python 当成代码执行。

正式批次的 `url` 和 `evidence_url` 必须属于配置来源域名或子域名。若招聘平台将原文放在不同域名，需要将其作为独立来源配置，避免错误归属。

来源受限时提交 `blocked` 空批次及原因；无匹配岗位但检索正常完成时提交 `ok` 空批次。不要把搜索摘要直接当成已核验岗位。

## 数据时效和去重

- `published_at`：来源明确提供的发布日期；未知则为 null。
- `updated_at`：原文更新时间，不替代发布日期。
- `first_seen_at` / `last_seen_at`：首次/最近观察；Codex 使用批次的 `collected_at`，导入旧文件不会刷新观察时间。
- `expires_at`：明确的截止时间。已过才标记 `expired`；无截止时间且长时间未核验则标记 `stale`。
- 岗位 ID 来自规范化原文 URL。仅移除 `utm_*`、`fbclid`、`gclid` 和 fragment；保留 `id`、`gh_jid`、`source`、`ref` 等可能区分岗位的参数。不会只按标题和公司合并不同城市岗位。
- 同一 URL 多来源合并时保留 `source_ids`。不同 URL 即使内容相似也保留，防止错误合并；此版本不做语义去重。
- 采集受页数限制或数据来源失败不会推断岗位已下架。历史岗位不会因单次列表遗漏而立即删除；超期后显示待复核。当前不自动硬删除待复核岗位，保持历史可追溯。

HTTP 请求限制响应大小为 5 MB，并检查公开地址、DNS、重定向、超时和有限重试。不能把本地浏览器 Cookie/登录态放进 GitHub Actions；此版本不实现账号登录、验证码处理或代理池。
