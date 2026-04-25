# CUA-Lark 后端

CUA-Lark 后端用于运行飞书桌面 GUI 自动化测试。当前实现重点是：截图诊断、运行模式可见性、mock/dry_run 基线、真实桌面安全 smoke、产品工作流模板、OCR/视觉混合定位、本地快速验证、可回放报告和 suite 级评估。

当前已真实验证通过的主链路：

- IM：搜索指定联系人/会话并在安全开关允许后发送消息。
- Docs：在云文档中新建空白文档，写入标题和正文，并验证内容可见。
- Calendar：在日历中新建测试日程，OCR 网格定位目标日期，填写时间并保存，最终用本地 OCR 验证日程可见。

## 快速开始

所有命令建议在 `agent` conda 环境中运行：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
```

复制配置模板：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写真实模型配置。不要提交 `.env`，不要把 API Key 或 Authorization header 写入日志、报告或 README。

PowerShell 中临时设置的环境变量优先级高于 `.env`。

## 推荐调试顺序

先确认截图链路健康：

```powershell
python cli.py screenshot-diagnostics --configured-only
python cli.py inspect-screen
```

再运行安全 IM smoke，不发送消息：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
python cli.py run-case cases\smoke_search_only.yaml --auto-debug
```

然后运行双产品安全 suite：

```powershell
python cli.py run-suite cases\safe_smoke_suite.yaml --auto-debug
```

最后才考虑受保护的真实 IM 发送。必须使用测试群或测试联系人：

```powershell
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"  # 可选：设置后只允许发给这个目标
python cli.py run-case cases\im_send_message_guarded.yaml --auto-debug
```

如果没有显式开启 `CUA_LARK_ALLOW_SEND_MESSAGE=true`，系统会阻止真实发送。`CUA_LARK_ALLOWED_IM_TARGET` 是可选白名单：留空时使用自然语言解析出的目标；设置后目标必须完全匹配，适合固定测试群/测试联系人。

## Docs / Calendar 创建闭环

Docs 和 Calendar 都属于真实写操作，默认会被安全开关阻止。建议先 dry-run 看解析和步骤，再打开创建开关做真实测试。

Docs dry-run：

```powershell
$env:DRY_RUN="true"
python cli.py run --instruction "在飞书云文档中新建一个测试文档，标题为「CUA Docs 自动化测试」，正文为「hello docs」" --show-intent
python cli.py run-case cases\docs_create_doc.yaml --auto-debug
```

Docs 真实创建测试文档：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
python cli.py run-case cases\docs_create_doc.yaml --auto-debug
```

Calendar dry-run：

```powershell
$env:DRY_RUN="true"
python cli.py run --instruction "打开飞书日历，创建一个会议，标题为「CUA Calendar 自动化测试」，时间为「明天 10:00」，参会人为「张三、李四」" --show-intent
python cli.py run-case cases\calendar_create_event.yaml --auto-debug
```

Calendar 真实创建测试日程：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
python cli.py run-case cases\calendar_create_event.yaml --auto-debug
```

通过标准：报告 `Status=pass`；`Parsed Intent` 里能看到文档标题/正文或日程标题/时间/参会人；`Runtime Mode` 里对应创建开关为 `True`；步骤报告能看到打开产品、点击创建、输入内容、保存或验证；最终截图中应能看到目标标题和内容。不要在真实业务空间里做第一次测试。

最近一次真实验证通过记录：

- Docs：`runs\reports\run_20260425_220621_3f36cadb`，`Status=pass`。
- Calendar：`runs\reports\run_20260425_234727_6d3a0cd2`，`Status=pass`。其中 `click_event_start_day` 使用 OCR 定位到 `(704, 986)`，最终 `verify_event` 由本地 OCR 确认 `title_hit=True, date_hit=True, time_hit=True`。

## CLI 命令

```powershell
python cli.py run --instruction "在飞书 IM 中搜索测试群，不发送消息" --product im
python cli.py run --instruction "给测试群发送一条消息：hello from CUA" --show-intent
python cli.py run-case cases\smoke_search_only.yaml --auto-debug
python cli.py run-suite cases\safe_smoke_suite.yaml --auto-debug
python cli.py screenshot-diagnostics --configured-only
python cli.py inspect-screen
```

如果省略 `--instruction`，CLI 会提示你在终端输入自然语言任务：

```powershell
python cli.py run --auto-debug
```

自然语言会先被解析成结构化意图，例如：

- `im_search_only`：搜索 IM 目标，但不发送消息。
- `im_send_message`：发送 IM 消息，会被路由到 guarded workflow。
- `docs_open_smoke`：打开或观察云文档入口，不创建、不编辑文档。
- `docs_create_doc`：创建测试文档，会被路由到 `docs_create_doc_guarded`，真实执行必须开启 `CUA_LARK_ALLOW_DOC_CREATE=true`。
- `calendar_create_event`：创建测试日程，会被路由到 `calendar_create_event_guarded`，真实执行必须开启 `CUA_LARK_ALLOW_CALENDAR_CREATE=true`。

可以只看解析结果、不执行桌面动作：

```powershell
python cli.py run --instruction "给测试群发送一条消息：hello from CUA" --show-intent
```

`--step-by-step` 会每一步等待人工确认；日常真实调试推荐 `--auto-debug`，它会自动执行，并在定位异常、窗口聚焦失败、动作失败或验证失败时停止。

## API 服务

Windows 上推荐以下两种启动方式，避免直接运行 `uvicorn.exe` 被系统拦截：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

或：

```powershell
python start_api.py
```

常用接口：

- `GET /health`
- `POST /runs`
- `POST /run-case`
- `POST /plan`
- `POST /observe`
- `GET /diagnostics/screenshot`
- `GET /runs/{run_id}`

## 运行模式与安全保护

- `DRY_RUN=true`：只验证流程和报告，不真实操作桌面。
- `CUA_LARK_PLACEHOLDER_SCREENSHOT=true`：允许 dry-run 下生成占位截图。
- `DRY_RUN=false`：真实桌面执行，运行前会做截图健康检查。
- `CUA_LARK_ALLOW_UNHEALTHY_SCREENSHOT=false`：截图疑似黑屏或纯色时默认阻止真实执行。
- `CUA_LARK_ALLOW_MOCK_REAL_EXECUTION=false`：真实执行时如果模型 provider 退回 mock，默认阻止点击。
- `CUA_LARK_AUTO_DEBUG=true` 或 `--auto-debug`：自动调试执行，异常即停。
- `CUA_LARK_ABORT_FILE=./runs/ABORT`：创建该文件可在下一步动作前中断运行。
- `CUA_LARK_ALLOW_SEND_MESSAGE=true`：允许真实发送 IM 消息。
- `CUA_LARK_ALLOW_DOC_CREATE=true`：允许真实创建测试云文档。
- `CUA_LARK_ALLOW_CALENDAR_CREATE=true`：允许真实创建测试日程。

## 当前示例用例

- `cases\smoke_search_only.yaml`：IM 搜索框安全 smoke，不发送消息。
- `cases\im_search_only.yaml`：IM 搜索目标安全用例，不进入会话，不发送消息。
- `cases\docs_open_smoke.yaml`：云文档入口安全 smoke，不创建、不编辑文档。
- `cases\safe_smoke_suite.yaml`：IM + Docs 安全 suite。
- `cases\im_send_message_guarded.yaml`：受保护 IM 发送，仅允许测试目标。
- `cases\docs_create_doc.yaml`：受保护 Docs 创建测试文档，需要 `CUA_LARK_ALLOW_DOC_CREATE=true` 才能真实创建。
- `cases\calendar_create_event.yaml`：受保护 Calendar 创建测试日程，需要 `CUA_LARK_ALLOW_CALENDAR_CREATE=true` 才能真实保存。
- `cases\im_send_message.yaml`：早期 IM 示例，建议优先使用 guarded 版本或自然语言 guarded flow。

## 定位与验证策略

真实桌面执行优先使用闭环定位，而不是固定坐标：

- IM 搜索结果：VLM 先给候选区域，OCR 必须确认目标联系人/会话文字，点击安全行区域。
- Docs 新建：进入云文档后 hover “新建”，OCR 点击“文档”，再点击“新建空白文档”的加号区域；浏览器文档编辑器打开后保持浏览器前台，不再强行切回飞书。
- Calendar 日期：先确认日期选择器弹层标题，再识别 7 列日期网格，根据 `event_date` 计算目标日格中心。日期关键点击禁止退回 VLM 猜测，避免误点到相邻日期或月份。
- 弹窗处理：使用 `conditional_hotkey` / `conditional_click`，只有视觉条件存在时才执行 Esc 或点击关闭。
- Calendar 最终验证：本地 OCR 检查日程标题、目标日期和时间，减少 VLM 对周视图/月视图的误判。

## 报告输出

每次 case 运行会生成：

```text
runs/reports/run_YYYYMMDD_HHMMSS_xxxxxxxx/
|-- summary.json
|-- summary.md
|-- steps.jsonl
|-- screenshots/
`-- artifacts/
```

suite 运行会生成：

```text
runs/reports/suite_YYYYMMDD_HHMMSS_xxxxxxxx/
|-- suite_summary.json
`-- suite_summary.md
```

报告会记录运行模式、真实/模拟状态、截图诊断、每一步 before/after 截图、坐标、输入、耗时、验证结果和失败原因。mock/dry_run 报告会明确提示模拟验证不代表真实飞书操作成功。

自然语言运行的报告还会包含 `Parsed Intent`，用于确认 Agent 如何理解你的需求，例如目标会话、消息内容、`plan_template` 和是否需要安全保护。

## 更多文档

- `docs/system_design.md`
- `docs/evaluation.md`
- `docs/demo_script.md`
- `ACCEPTANCE.md`

## API 怎么理解和验证

API 是把 CLI 能力包装成 HTTP 服务，方便前端页面或其他程序调用。它不是另一套 Agent 逻辑，底层仍然复用同一套截图、规划、执行、验证和报告链路。只在本机调试时，CLI 更简单；需要被网页或外部脚本调用时，再启动 API。

启动服务：
```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
python start_api.py
```

或：
```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

最小验收：
```powershell
curl http://127.0.0.1:8000/health
```

返回 JSON 里 `status=ok` 就说明服务启动正常。

安全查看计划，不执行桌面动作：
```powershell
$body = @{
  task = "在IM中搜索测试群，发送一条消息：hello from CUA"
  product = "im"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/plan `
  -ContentType "application/json" `
  -Body $body
```

安全 dry-run 运行自然语言任务：
```powershell
$body = @{
  task = "在IM中搜索测试群，发送一条消息：hello from CUA"
  product = "im"
  dry_run = $true
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/runs `
  -ContentType "application/json" `
  -Body $body
```

运行 YAML 用例：
```powershell
$body = @{
  path = "cases\smoke_search_only.yaml"
  dry_run = $true
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/run-case `
  -ContentType "application/json" `
  -Body $body
```

截图诊断：
```powershell
Invoke-RestMethod http://127.0.0.1:8000/diagnostics/screenshot
```

查询报告：
```powershell
Invoke-RestMethod http://127.0.0.1:8000/runs/<run_id>
```

API 算没问题的标准：
- `python start_api.py` 能启动。
- `/health` 返回 200 和 `status=ok`。
- `/plan` 能返回结构化步骤，且不会点击桌面。
- `/diagnostics/screenshot` 能返回截图诊断结果。
- `/runs` 和 `/run-case` 在 `dry_run=true` 时能生成报告但不真实操作桌面。
- `dry_run=false` 时，截图健康检查、mock 真实执行保护、发送安全开关仍然生效。
