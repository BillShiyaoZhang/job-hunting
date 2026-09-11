# 交付验证记录

验证日期：2026-09-11。本次只在本地执行，没有部署、推送或触发真实定时任务。

## 已通过

- Python 后端 **18 项测试**：配置校验、空数组覆盖、any/all 与排除词/地点过滤、发布日期限制、URL 去重、跨来源溯源、停用来源保留、旧批次事实保护、时区排序、过期/待复核区分、失败保留历史、HTML 清洗及危险 URL 拒绝。
- 适配器固定响应测试覆盖 Greenhouse、Lever 分页与工作方式、RSS/Atom 日期与链接、拒绝伪装成 feed 的 HTML、JSON-LD graph/远程/薪资提取。
- 端到端离线测试：模拟公开 API 与 Codex batch 输入 → 策略过滤 → 合并 → 正式静态构建；确认生成的数据、来源与运行记录一致。测试只使用临时目录，不污染示例数据。
- Node **6 项测试**：中文与多词搜索、来源交集、状态/地点/远程过滤、未知发布日期排序、安全跳转、配置错误处理及关键词输入。
- `node --check`：前端两个模块均通过语法检查。
- `python -m jobradar validate`：当前 6 个来源配置与 12 条示例岗位有效。
- `python -m jobradar build` 和 `python scripts/check_site.py`：9 个预期静态文件完整，入口引用可解析，全部本地路径兼容 GitHub Pages 仓库子路径；未把后端、任务提示词或私有目录放进发布目录。
- 正式构建拒绝示例数据，未启用来源时采集拒绝执行，演示命令默认拒绝覆盖正式数据。
- 本地静态 HTTP 服务返回 200；可通过 `http://127.0.0.1:8765/` 访问。
- 两轮独立静态代码审查，修复了旧 inbox 回滚事实、时区排序、跨来源主来源停用、通用查询参数误去重、Lever 工作方式映射，以及刷新工作流未执行 CI 检查/失败报告/Pages 读取权限问题。

## 工作流检查

三个 YAML 已做静态审查。生产刷新与发布均需显式变量开关且限制默认分支；计划 cron 保持注释。同一刷新 run 上传和发布当前产物，避免依赖 GITHUB_TOKEN push 再触发 CI。刷新失败会附带本次阶段结果，旧报告不会冒充本次采集结果。`checkout@v6`、`setup-python@v6` 及 Pages actions 的用法已对照官方资料检查。

本机未提供 YAML 校验器或 actionlint，未在 GitHub 执行工作流。真实仓库的组织权限、分支保护和 Pages environment 仍需在未来启用时验证。

## 尚未执行的验证

- 真实招聘源网络采集：目标公司招聘板、关键词和来源尚未由用户配置，默认全部关闭。
- BOSS/猎聘等网站登录可用性和浏览器检索：本次未运行 Codex 任务；站点访问限制可能导致 blocked。
- 浏览器交互与视觉 QA：未执行点击、截图或移动端浏览器测试；已进行模块语法、业务逻辑与静态引用检查。
- 可选 WebMCP 工具：采用能力检测注册文本筛选工具；当前没有已授权的支持环境进行运行时验证。不影响普通浏览器使用。
- GitHub Actions、GitHub Pages 和 Codex scheduled task 的远端端到端执行：遵循“先不要部署”要求，未启用。

复现测试：

```bash
python -m unittest discover -s tests -v
node --test tests/frontend.test.mjs
node --check dist/app.mjs
node --check dist/lib.mjs
python -m jobradar validate
python -m jobradar build
python scripts/check_site.py
```

测试使用 `tests/fixtures/search.json`，不会因为用户更换真实来源而依赖某家网站或向外发起请求。
