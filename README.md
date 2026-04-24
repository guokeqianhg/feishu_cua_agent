# CUA-Lark 后端

这是 CUA-Lark 智能测试 Agent 的后端实现。当前重点是从 `mock + dry_run` 的本地验证，逐步走向真实飞书桌面验证。

当前架构：

- Python 作为主运行时。
- FastAPI 提供服务接口。
- LangGraph 编排 Agent 执行流程。
- MSS/Pillow 进行截图采集，并提供截图健康诊断。
- PyAutoGUI/Pyperclip 执行桌面鼠标键盘操作。
- OpenAI-compatible LLM/VLM 适配层，并提供确定性的 Mock Provider。
- 每次运行都会输出结构化 JSON 报告和 Markdown 报告。

## 本地运行

所有命令都在 `agent` conda 环境中执行：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
```

## 配置文件

后端启动时会自动读取：

```text
backend\.env
```

你可以先复制示例文件：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写模型 API 配置：

```text
CUA_LARK_MODEL_PROVIDER=auto
OPENAI_API_KEY=replace_me
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL_TEXT=qwen-plus
OPENAI_MODEL_VISION=qwen-vl-max
```

常用运行配置也可以写在同一个文件里：

```text
DRY_RUN=true
CUA_LARK_PLACEHOLDER_SCREENSHOT=true
CUA_LARK_MONITOR_INDEX=1
CUA_LARK_STEP_BY_STEP=false
CUA_LARK_AUTO_DEBUG=false
```

读取规则：

- 默认读取 `backend\.env`。
- PowerShell 里手动设置的环境变量优先级更高，会覆盖 `.env`。
- 如果想指定其它配置文件，可以设置 `CUA_LARK_ENV_FILE`。

示例：

```powershell
$env:CUA_LARK_ENV_FILE="D:\找工作\feishu_cua_agent\backend\.env.real"
python cli.py run-case cases\smoke_search_only.yaml
```

建议不要把 `.env` 提交到仓库，只提交 `.env.example`。

## 截图诊断

真实桌面操作前，建议先确认 MSS 能抓到正常屏幕，而不是黑屏或纯色图：

```powershell
$env:CUA_LARK_MODEL_PROVIDER="mock"
$env:DRY_RUN="true"
python cli.py screenshot-diagnostics
```

输出会包含：

- 当前可用 monitors 信息。
- 每个显示器的诊断截图路径。
- 每张截图的亮度均值、方差、是否疑似黑屏或纯色。
- 可能原因，例如远程桌面、锁屏、权限、抓错显示器、显示器编号错误等。

诊断截图会保存到：

```text
runs/diagnostics/screenshot_YYYYMMDD_HHMMSS_xxxxxxxx/
```

只检查配置中的显示器编号：

```powershell
$env:CUA_LARK_MONITOR_INDEX="1"
python cli.py screenshot-diagnostics --configured-only
```

输出完整 JSON：

```powershell
python cli.py screenshot-diagnostics --json
```

## 坐标校准和屏幕调试

如果要判断点击坐标是否合理，可以生成一张带网格和当前鼠标位置的截图：

```powershell
python cli.py inspect-screen
```

可以调整网格间距：

```powershell
python cli.py inspect-screen --grid-size 80
```

输出会包含：

- 当前 `CUA_LARK_MONITOR_INDEX`
- 截图宽高
- 当前鼠标位置
- 带坐标网格的截图路径

## Mock 本地验证

如果只是做本地确定性验证，不希望真实操作飞书桌面客户端，可以使用 `mock + dry_run`：

```powershell
$env:CUA_LARK_MODEL_PROVIDER="mock"
$env:DRY_RUN="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="true"
python cli.py run-case cases\im_send_message.yaml
```

预期会看到类似输出：

```text
Run pass: 7/7 steps passed. Product=im. Evidence complete=True.
report_dir=runs\reports\run_YYYYMMDD_HHMMSS_xxxxxxxx
summary_json=runs\reports\run_YYYYMMDD_HHMMSS_xxxxxxxx\summary.json
summary_md=runs\reports\run_YYYYMMDD_HHMMSS_xxxxxxxx\summary.md
```

如果当前机器截图是黑屏或纯色，`Evidence complete` 会显示为 `False`，报告的 `Warnings` 会说明截图异常原因。

## 逐步执行模式

CLI 支持 action preview / step-by-step 模式。开启后，每一步真正执行前都会打印：

- action
- target
- input text
- hotkeys
- 候选点击坐标
- bbox
- before screenshot 路径

然后等待人工输入：

- `y`：继续执行当前步骤。
- `n`：跳过当前步骤。
- `q`：终止运行并生成 `aborted` 报告。

通过 CLI 参数开启：

```powershell
python cli.py run-case cases\smoke_search_only.yaml --step-by-step
```

或通过环境变量开启：

```powershell
$env:CUA_LARK_STEP_BY_STEP="true"
python cli.py run-case cases\smoke_search_only.yaml
```

报告中的 `steps.jsonl`、`summary.json` 和 `summary.md` 会记录每一步是否经过用户确认、实际坐标、输入文本、热键、dry_run 状态、验证结果和失败原因。

注意：`mock` 或 `dry_run` 模式只说明流程和报告链路通过，不代表真实飞书操作成功。报告中的 `Runtime Mode` 和 `Warnings` 会明确标注这一点。

## 启动 API 服务

Windows 上推荐下面两种方式，避免直接运行 `uvicorn.exe` 时被 Windows 智能应用控制拦截。

方式一：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

方式二：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
python start_api.py
```

启动后访问：

```text
http://127.0.0.1:8000/docs
```

## API 接口

- `GET /health`：查看服务健康状态和当前运行模式。
- `POST /runs`：运行一条自然语言测试任务。
- `POST /run`：兼容旧接口，行为等同于 `/runs`。
- `POST /run-case`：运行 YAML 测试用例。
- `POST /plan`：只生成结构化计划，不执行操作。
- `POST /observe`：截图并返回当前屏幕观察摘要。
- `GET /diagnostics/screenshot`：执行截图诊断。
- `GET /runs/{run_id}`：读取已经落盘的运行报告。

## API 自检示例

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/observe" -Method Post
Invoke-RestMethod -Uri "http://127.0.0.1:8000/diagnostics/screenshot"
```

## 真实模型 smoke 调试流程

`.env` 可以放真实模型配置，但不要提交 `.env`，也不要把 API Key 或 Authorization header 写入日志、报告或 README。程序启动时会自动读取 `backend\.env`，PowerShell 中临时设置的环境变量优先级更高。

推荐按下面顺序调试真实桌面链路：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend

python cli.py screenshot-diagnostics --configured-only
python cli.py inspect-screen

$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
python cli.py run-case cases\smoke_search_only.yaml --step-by-step
```

`smoke_search_only.yaml` 是安全 smoke 用例，只验证飞书窗口、搜索框聚焦、输入 `harmless-smoke-test` 和截图证据；它不会发送消息，不会点击聊天结果进入会话，也不会使用 Enter 发送聊天内容。当前实现会优先使用 `Ctrl+K` 聚焦搜索，并通过剪贴板粘贴文本，降低中文输入法导致的不稳定。

step-by-step 提示中会额外显示：

- `locator_source`：定位来源，例如 `vlm`、`ocr`、`mock`、`manual`。
- `confidence`：定位置信度。
- `bbox_area_ratio`：候选框占屏幕面积比例。
- `warnings`：候选框过大、中心点不在预期区域等风险。
- `recommended_action`：建议继续、跳过、终止或手动坐标。
- `active_window_title`：执行前的当前前台窗口标题，用来确认快捷键是否会打到飞书窗口。

交互输入支持：

- `y`：按当前候选继续执行。
- `n`：跳过当前步骤。
- `q`：终止运行并生成 `status=aborted` 报告。
- `c x y`：使用手动坐标执行本步骤，例如 `c 120 300`。报告会记录 `manual_override=true` 和实际执行坐标。

如果不想每一步都手动输入 `y`，推荐使用自动调试模式。它会打印每一步的 action preview，然后自动执行；如果定位 warning、窗口聚焦失败、动作失败或真实 VLM 验证失败，会自动中断并生成失败报告：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
python cli.py run-case cases\smoke_search_only.yaml --auto-debug
```

`--step-by-step` 只建议在需要人工坐标覆盖 `c x y` 时使用；常规 smoke 调试请优先使用 `--auto-debug`。

`smoke_search_only.yaml` 走本地快速验证路径：不会每一步都调用 VLM，因此不会因为模型 JSON 解析失败而卡住，也会明显更快。它通过截图健康、窗口标题、搜索弹窗区域变化、输入框区域变化等本地证据判断 smoke 是否通过。复杂任务仍会使用真实 VLM。

安全保护：当 `DRY_RUN=false` 但 `effective_model_provider=mock` 时，系统默认禁止真实点击，避免模型配置失败回退到 mock 后还继续操作桌面。只有在你明确知道风险时，才设置：

```powershell
$env:CUA_LARK_ALLOW_MOCK_REAL_EXECUTION="true"
```

只有当截图诊断健康、`inspect-screen` 坐标合理、`smoke_search_only.yaml --step-by-step` 的截图/坐标/输入证据都稳定后，才进入 `im_send_message.yaml` 的完整 IM 发消息测试。完整发消息测试请先使用测试群和无害文本，不要在重要聊天窗口里测试。

真实执行时，如果真实 VLM 验证失败并回退到 mock，系统会把该步骤标为失败，而不是继续给出 pass。这样可以避免“动作没成功，但 mock verification 让报告变绿”的误判。

如果截图突然变黑，先看 `screenshot-diagnostics` 的原始 MSS 结果。如果所有 monitor 都是 `mean=0.0, stdev=0.0`，通常说明当前 Windows 桌面会话不可捕获，例如远程桌面被最小化、锁屏、权限/安全软件阻止或 GPU/驱动返回保护帧。普通运行链路会自动尝试其它 monitor 和备用截图方式；如果仍失败，会明确写入 `Screenshot warning`，并在允许 placeholder 的 dry-run 场景下生成占位截图，不再把黑屏当作正常 evidence。

相关开关：

```powershell
$env:CUA_LARK_AUTO_SELECT_HEALTHY_MONITOR="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"  # 真实运行建议关闭
```

运行自然语言任务：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/runs" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"task":"在IM中搜索「测试群」，发送一条消息「Hello World」，并确认发送成功","product":"im"}'
```

运行 YAML 用例：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/run-case" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"path":"cases\\im_send_message.yaml"}'
```

## 报告输出

每次运行都会生成独立目录：

```text
runs/reports/run_YYYYMMDD_HHMMSS_xxxxxxxx/
|-- summary.json
|-- summary.md
|-- steps.jsonl
|-- screenshots/
`-- artifacts/
```

报告会额外显示：

- `model_provider`
- `effective_model_provider`
- `dry_run`
- `placeholder_screenshot`
- `real_desktop_execution`
- `mock_verification`
- 截图诊断结果
- 黑屏或纯色截图 warning

如果报告提示“这是模拟验证，不代表真实飞书桌面操作成功”，说明当前结果只能用于验证流程链路。

## 真实飞书操作前检查

真实执行前建议按顺序完成：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
python cli.py screenshot-diagnostics
python cli.py inspect-screen
```

确认至少有一个显示器截图不是黑屏或纯色后，先运行安全 smoke 用例。这个用例只定位/输入搜索框，不发送聊天消息：

```powershell
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:OPENAI_API_KEY="replace_me"
$env:OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:OPENAI_MODEL_TEXT="qwen-plus"
$env:OPENAI_MODEL_VISION="qwen-vl-max"
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MONITOR_INDEX="1"
python cli.py run-case cases\smoke_search_only.yaml --step-by-step
```

当 `DRY_RUN=false` 时，系统会先执行截图健康检查。如果截图疑似黑屏或纯色，默认会阻止真实点击。只有明确设置下面变量才会强制继续：

```powershell
$env:CUA_LARK_ALLOW_UNHEALTHY_SCREENSHOT="true"
```

不建议在没有确认屏幕可见性的情况下强制继续。

真实桌面调试推荐顺序：

1. `python cli.py screenshot-diagnostics`
2. `python cli.py inspect-screen`
3. 启动 API 后调用 `/observe`，确认截图观察链路可用。
4. `DRY_RUN=false` + `--step-by-step` 运行 `cases\smoke_search_only.yaml`。
5. 确认报告里真实坐标、输入文本、截图证据都合理。
6. 最后再运行 `cases\im_send_message.yaml`。

请不要在重要聊天窗口里测试。完整发送消息前，先使用测试群和无害文本。

## 安全中断

真实执行过程中可以通过两种方式中断：

- 在 CLI 中按 `Ctrl+C`，系统会尽量生成 `status=aborted` 的报告。
- 创建 `runs\ABORT` 文件，系统会在下一步动作前停止。

PowerShell 示例：

```powershell
New-Item -ItemType File runs\ABORT
```

清除中断文件：

```powershell
Remove-Item runs\ABORT
```

## 示例用例

当前提供三个 YAML 示例：

- `cases\im_send_message.yaml`：IM 搜索群聊并发送消息。
- `cases\docs_create_doc.yaml`：创建云文档并输入标题。
- `cases\calendar_create_event.yaml`：创建日历会议。
- `cases\smoke_search_only.yaml`：安全真实桌面 smoke，不发送消息。

运行方式：

```powershell
python cli.py run-case cases\im_send_message.yaml
python cli.py run-case cases\docs_create_doc.yaml
python cli.py run-case cases\calendar_create_event.yaml
python cli.py run-case cases\smoke_search_only.yaml
```

## 最小自检清单

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
$env:CUA_LARK_MODEL_PROVIDER="mock"
$env:DRY_RUN="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="true"

python cli.py screenshot-diagnostics
python cli.py inspect-screen
python cli.py run-case cases\im_send_message.yaml
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

服务启动后另开一个 PowerShell：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/observe" -Method Post
Invoke-RestMethod -Uri "http://127.0.0.1:8000/diagnostics/screenshot"
```
