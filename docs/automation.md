# 自动化、批次协议与未来启用

## 当前状态

项目已准备完整工作流，但未创建远程仓库、未推送、未配置 Pages、未创建 Codex 定时任务。所有来源默认 disabled，所有生产工作流均有显式开关；cron 仍是注释。CI 只执行离线验证，不会采集或部署。

## 三个 GitHub 工作流

| 文件 | 触发与职责 | 默认行为 |
| --- | --- | --- |
| `.github/workflows/ci.yml` | push/PR/手动：配置、数据、后端测试、前端测试、静态构建 | 上传项目后可运行，只读，不部署 |
| `.github/workflows/refresh.yml` | 手动，或 inbox/config 的 push；未来可取消 schedule 注释 | 缺少 `ENABLE_JOB_REFRESH=true` 时跳过；只允许默认分支 |
| `.github/workflows/pages.yml` | 手动发布已保存的真实数据 | 缺少 `ENABLE_PAGES_DEPLOY=true` 时跳过；只允许默认分支 |

刷新工作流会先采集并构建，再限定路径提交 `data/jobs.json`、`data/runs/*` 和 `dist/data/*`。如果启用 Pages，在同一次工作流上传产物并调用后续部署 job。不会指望 `GITHUB_TOKEN` 产生的 commit 再触发另一个 push 工作流。[GitHub token 官方行为](https://docs.github.com/en/actions/concepts/security/github_token)

刷新与手动发布共享串行 concurrency group。失败的 push 不强推、不自动覆盖远端；本次不会继续部署，报告作为 Actions artifact 保留 14 天。源内临时错误有限重试，单源失败保留历史；所有启用来源都失败或等待时，CLI 返回非零使 Actions 报错。部分成功时输出 partial 和逐源原因。

当前工作流使用仓库内置 GITHUB_TOKEN；公开 API 采集不需要额外密钥。若默认分支有保护规则而禁止机器人直接提交数据，refresh 会在 push 阶段停止。未来应按仓库策略将保存步骤改为数据 PR 或单独的数据分支，不要为脚本绕过保护。

## Codex 定时任务

任务模板在 `automation/codex-task.md`；参数备忘在 `automation/task-preset.json`。后者只是本项目自定义 JSON，不是 Codex 内部配置，不会自行创建任务。

建议每天北京时间 09:10 和 21:10 运行，或根据来源更新频率调整。未来可以在 Codex 桌面 App 创建绑定此项目的定时任务，复制完整提示词。本地运行需要电脑开机、App 运行及项目目录可用；默认沙箱和工具授权也需要预先确认。Git 项目可选本地目录或 worktree，CLI 本身没有定时任务管理界面。[OpenAI 官方 Scheduled tasks](https://learn.chatgpt.com/docs/automations?surface=app)

这与在 GitHub CI 中运行 `openai/codex-action` 是不同机制。本项目无需 OpenAI API key，也没有偷偷创建 API 调用。若将来改用 Codex GitHub Action，需另行准备该模式的认证和资源配置。[OpenAI 官方 GitHub Action](https://learn.chatgpt.com/docs/github-action)

### 交接模式

| 模式 | 发生什么 | 自动化程度 |
| --- | --- | --- |
| local，当前默认 | Codex 生成并校验本地 inbox | 人工审阅并提交后才进入 GitHub |
| PR，未来显式授权 | Codex 提交独立分支并创建 PR | 需要合并；不是完全无人值守刷新 |
| 直接推送，未来显式授权 | 专用干净 checkout 同步默认分支，只推送本轮 inbox | 推送后 refresh 自动处理；要求认证、分支策略和开关已就绪 |

未来选择 PR/推送模式时，修改任务提示词中的明确交接模式，先手动演练一轮，再创建计划。不要认为仅配置了时间就会自动拥有网络、浏览器或 GitHub 写权限。

## Inbox 协议

每个 JSON 批次对应一个来源，字段如下：

| 字段 | 约束 |
| --- | --- |
| `schema_version` | 1 |
| `source_id` | 配置中存在且适配器为 codex |
| `collected_at` | 真实观察时间，ISO 8601，推荐 UTC Z；不得超过当前时间 5 分钟 |
| `status` | ok / blocked / error |
| `coverage` | partial |
| `message` | 简短的检索范围或受阻说明 |
| `jobs` | 最多 1000 条；非 ok 状态必须为空 |

单条岗位必须包含 `title`、`url`、`evidence_url`。URL 必须属于该来源域名或其子域，不得含凭据或指向内部地址。其他字段使用任务模板中的名称。`workplace` 可为 remote/hybrid/onsite/unknown；缺失事实留空，日期为 null 或 ISO 8601。

不要直接提交网页 HTML、完整 Cookie、账户信息、无关个人资料或搜索摘要作为岗位事实。description 应为简短的客观岗位摘要，后端还会转为纯文本，前端不会将其作为 HTML 插入。

导入示例：

```bash
python -m jobradar import .local/my-batch.json
python -m jobradar validate
python -m jobradar collect
python -m jobradar build
```

前两步仅导入和校验，后两步才合并和更新本地站点。实际 import 生成的 `data/inbox/*.json` 应随 Git 提交，才能被 Actions 看见；`.local/`、`*.local.json` 与 `data/inbox/example.json` 不参与实际导入。示例文件用于说明受阻状态，并始终跳过。

重复导入相同内容会使用同名哈希文件；重放旧批次不会把新标题/薪资改回旧值，也不会刷新 last_seen。批次按解析后的真实时间排序，可正确处理带时区的 ISO 日期。扫描保留全部 inbox 是当前简单实现；长期使用可在备份和保留最新已导入状态后归档旧批次，不要在尚未合并时删除。

## 未来启用清单（本次不执行）

1. 创建或选择 GitHub 仓库，上传本项目，保留 `.github/workflows`、配置、源数据与 `dist`。
2. 填写自己的真实来源和关键词，先本地执行 validate、plan、collect、build，检查运行记录。
3. 在仓库 Actions variables 中显式设置 `ENABLE_JOB_REFRESH` 为字符串 `true`，授予该工作流所需的 contents 写权限；先手动运行刷新。
4. 若需要 GitHub 定时采集，取消 `refresh.yml` 的 schedule 注释。示例 `37 0,12 * * *` 为 UTC 00:37/12:37，即北京时间 08:37/20:37。
5. 按上文选择并授权 Codex 交接模式，先手动验证工具和批次，再在 App 创建定时任务。两种时间表独立；inbox push 会额外触发一次刷新。
6. **准备发布时**才在 Pages 设置中选择 GitHub Actions，并显式设 `ENABLE_PAGES_DEPLOY=true`。在默认分支手动运行 Publish Pages manually，或等待下一次刷新工作流。
7. 在 `github-pages` environment 配置符合团队要求的默认分支规则；如需人工批准，在该环境设置 reviewer。

Pages 发布使用 configure-pages、upload-pages-artifact 和 deploy-pages，部署 job 单独授予 pages:write 与 id-token:write。只上传 `dist/`，不会上传整个仓库。[GitHub Pages 自定义工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

GitHub 定时任务运行默认分支，可能延迟；公开仓库长时间无活动会自动停用计划任务。不要把它当成精确实时调度器。[GitHub 事件与 schedule 说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

## 常见问题

- **网页保存配置后检索没变化**：这只是浏览器草稿。导出并更新仓库配置，校验后重新采集和构建。
- **首次 collect 失败**：默认来源全部关闭。填写真实参数并启用；仅 Codex 来源还需要批次。
- **页面有岗位但来源未启用**：初始页面是明确标记的虚构示例，来源状态表示真实采集开关。
- **全部采集失败后网页还是旧数据**：这是保留历史机制。查看 Actions 附件或本地 `data/runs/latest.json`。失败工作流不会部署；需修复后重新运行。可本地 build 查看最新失败记录。
- **部分失败没有清空岗位**：失败或有限覆盖不能证明职位已下架；超过复核期限会显示待复核。
- **Pages 构建拒绝 demo**：先采集真实数据；不要删除示例标记绕过检查。
- **网页按钮不能直接执行 GitHub Action**：静态网页不持有 GitHub 凭据；在仓库 Actions 或 Codex 授权的工具中操作。
- **远程岗位实际不能异地申请**：workplace 来自原文标记，具体地区和用工约束仍以职位原文为准。
