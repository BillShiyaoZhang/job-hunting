# 工作雷达 · Job Radar

可托管在 **GitHub Pages** 的招聘岗位整合站点，配套 **GitHub Actions + Codex 定时任务** 数据流水线。前端是原生 HTML/CSS/JavaScript，后端使用 Python 标准库，无数据库、无付费 API 依赖、无需 npm install。

**当前交付状态：仅本地准备，未部署，未创建远程仓库，未启用定时任务。** 所有招聘来源默认关闭；自带 12 个明确标记的虚构岗位用于预览。正式构建会拒绝示例数据。

## 本地打开

Windows PowerShell，在项目目录运行：

```powershell
.\scripts\local.ps1 serve
```

打开 [本地预览](http://127.0.0.1:8765/)。脚本优先识别 Codex 自带 Python，也支持 PATH 上的 Python。若端口被占用，可添加 `-Port 8766`。按 Ctrl+C 停止服务。

其他系统需要 Python 3.11+（推荐 3.12）：

```bash
python -m jobradar build
python -m http.server 8765 --bind 127.0.0.1 --directory dist
```

不要直接双击 `index.html`，页面通过 HTTP 加载 JSON。`dist/` 既是可维护的前端源文件目录，也是最终静态发布目录，所有路径均支持 `用户名.github.io/仓库名/` 子路径。

## 已包含的能力

- **岗位发现**：关键词搜索、地点/来源/远程方式/状态筛选、排序、分页、岗位详情和原文跳转。
- **招聘来源**：添加或编辑来源、启停开关、接口参数、来源专属检索策略。
- **检索配置**：关键词、排除词、地点、任意/全部匹配、检索字段、结果与页数上限、时效、超时、重试和请求间隔；支持 JSON 导入导出。
- **数据流水线**：Greenhouse、Lever、RSS/Atom、JSON-LD 职位页、Codex 核验批次；数据校验、URL 去重、来源溯源、旧批次重放保护、失败保留和复核期限。
- **运行记录**：每个来源的采集状态、读取/入选数量和问题说明，保留最近 30 次记录。
- **自动化准备**：只读 CI、带开关的刷新工作流、单独手动发布工作流、Codex 定时任务提示词及文件协议。

网页中的配置保存为**浏览器本地草稿**，不会更改 GitHub 仓库或启动采集。导出 `search.json`，替换仓库的 `config/search.json`，再运行校验，才能供后端采用。不要把密码、Cookie 或令牌放入配置；构建后的配置公开可读。

## 命令

| 命令 | 用途 |
| --- | --- |
| `python -m jobradar validate` | 校验配置、岗位数据和待导入批次 |
| `python -m jobradar plan` | 输出启用来源的最终策略及 Codex 查询词 |
| `python -m jobradar collect` | 执行真实采集并合并 inbox；至少启用一个来源 |
| `python -m jobradar import /path/to/batch.json` | 校验 Codex 批次并保存到本地 inbox |
| `python -m jobradar build` | 更新静态数据，允许示例预览 |
| `python -m jobradar build --production` | 正式构建，拒绝示例数据 |
| `python -m jobradar demo` | 重建示例；默认不会覆盖正式数据 |
| `python -m unittest discover -s tests -v` | 后端离线测试 |
| `node --test tests/frontend.test.mjs` | 前端筛选及配置测试，需要 Node 20+ |
| `python scripts/check_site.py` | 检查静态文件清单和子路径兼容性 |

Windows 也可运行 `.\scripts\local.ps1 validate`、`plan`、`demo`、`collect`、`build`、`test`。使用其他配置时，将全局参数写在子命令之前：`python -m jobradar --config config/my-search.json plan`。

## 如何开始真实检索

1. 在「招聘来源」编辑目标来源。公开招聘板填写真实公司标识；BOSS、猎聘等使用 Codex 策略。
2. 在「检索配置」设置自己的关键词和地点，保存并导出配置到 `config/search.json`。
3. 运行 `validate` 和 `plan`，确认启用的来源和最终策略。
4. API/订阅源运行 `collect`；Codex 来源按任务模板核验岗位，然后 `import` 批次，再 `collect`。
5. 运行 `build` 并刷新本地页面。此过程不部署。

如只启用 Codex 来源、但没有任何可用批次，采集会显示等待或失败，并保留现有数据。没有结果时不会自动混入示例岗位。

## 自动化如何衔接

```mermaid
flowchart LR
    C[仓库检索配置] --> A[GitHub Actions：公开接口 / RSS]
    C --> X[Codex 定时任务：浏览器检索与核验]
    X --> I[结构化 inbox JSON]
    I --> G[本地审阅 / PR 合并 / 授权后推送]
    G --> P[Python 校验、过滤、去重与时效处理]
    A --> P
    P --> D[data/jobs.json + 运行记录]
    D --> S[dist 静态站点]
    S --> O[未来显式开启 Pages 发布]
```

两种调度通过仓库中的文件衔接。Codex 桌面任务并非由 GitHub Actions 内置唤醒；本地任务需要设备和 App 保持运行。[Codex 官方定时任务文档](https://learn.chatgpt.com/docs/automations?surface=app)

`refresh.yml` 在同一次运行中采集、提交数据、构建，并在未来打开发布开关后部署该次产物。它不会依赖机器人提交再触发另一次 push 工作流，因为 `GITHUB_TOKEN` 的 push 不会产生这种触发。[GitHub 官方说明](https://docs.github.com/en/actions/concepts/security/github_token)

## 文件入口

| 路径 | 内容 |
| --- | --- |
| `dist/` | 静态前端和可发布数据 |
| `config/search.json` | 唯一的后端检索配置 |
| `jobradar/` | 校验、采集适配器、合并、构建和命令行 |
| `data/jobs.json` | 持久岗位数据；采集失败仍保留历史 |
| `data/inbox/` | Codex 核验批次；`example.json` 永远不导入 |
| `data/runs/` | 最新运行与最近 30 次历史 |
| `.github/workflows/` | CI、数据刷新与手动 Pages 发布 |
| `automation/codex-task.md` | 可复制到 Codex 的完整定时任务提示词 |
| `automation/task-preset.json` | 尚未创建的任务参数备忘，不会自行执行 |
| `docs/configuration.md` | 配置字段、来源接入及覆盖规则 |
| `docs/automation.md` | 衔接协议、未来启用、权限与排错 |
| `docs/verification.md` | 已执行验证及未验证范围 |

公开接口适配器已通过离线固定响应测试。BOSS、猎聘仅提供可配置的 Codex 检索入口，不宣称支持直接爬取；登录、验证码或访问限制会记录为受阻。真实站点可用性需要在填入目标来源后验证。
