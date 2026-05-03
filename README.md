# CUA-Lark 后端

CUA-Lark 后端是一个面向飞书桌面端的 Computer-Use Agent 测试框架。它不依赖飞书开放平台 API 完成业务动作，而是像真实用户一样观察屏幕、理解自然语言、规划操作步骤、执行鼠标键盘动作，并用截图、OCR、视觉定位和本地验证生成可回放测试报告。

当前项目已经覆盖 IM、Docs、Calendar、VC 四个飞书子产品，核心功能测试均已跑通，进入最终回归证据整理和交付材料打磨阶段。

## 核心能力

- 视觉感知：截图采集、飞书窗口检测、OCR 文本识别、CV/像素状态判断、截图健康诊断。
- 语义理解：自然语言指令解析为结构化 intent，并路由到对应产品 workflow。
- 自主操作：支持点击、双击、右键、hover、滚动、拖拽、文本输入、快捷键、窗口聚焦、条件点击和条件快捷键。
- 状态验证：每步执行后用 OCR、截图 diff、产品状态规则和错误库验证结果。
- 安全防护：真实发送、创建、分享、修改日程、发起/加入会议、切换设备都需要显式环境变量授权。
- 评估报告：每次运行生成 `summary.md`、`summary.json`、`steps.jsonl`、before/after 截图和诊断证据。

## 覆盖范围

IM：

- 搜索会话和聊天记录。
- 发送文本消息。
- 发送图片消息。
- 创建群组。
- @ 提及成员。
- 对指定消息添加点赞表情回复。

Docs：

- 打开云文档入口。
- 新建测试文档。
- 输入标题和正文。
- 插入标题和列表。
- 分享文档给允许的测试联系人。

Calendar：

- 创建测试日程。
- 邀请参会人。
- 修改日程时间。
- 查看联系人忙闲状态，不保存日程。

VC：

- 发起视频会议。
- 发起命名会议。
- 加入指定会议 ID。
- 发起/加入后控制摄像头和麦克风。
- 已在会议中独立切换摄像头和麦克风。

## 快速开始

每次打开新的 PowerShell 后先进入项目环境：

```powershell
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"
conda activate agent
cd path\to\feishu_cua_agent
```

复制配置模板：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写真实模型配置。不要提交 `.env`，不要把 API Key、Authorization header、cookie 或真实 token 写入日志、报告或 README。PowerShell 中临时设置的环境变量优先级高于 `.env`。

真实桌面执行的基础配置：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

如果真实模型未配置好，系统会因为 `effective_model_provider=mock` 阻止真实点击。除非明确接受风险，不要设置 `CUA_LARK_ALLOW_MOCK_REAL_EXECUTION=true`。

## 设备和截图校验

这类命令只检查环境，不执行业务动作：

```powershell
python cli.py screenshot-diagnostics --configured-only
python cli.py inspect-screen
```

如果截图异常、飞书窗口不在可见屏幕、远程桌面黑屏或显示器配置不对，应先修复环境，再跑真实测试。

## 自然语言解析校验

使用 `--show-intent` 可以只看解析结果，不点击桌面：

```powershell
python -B cli.py run --product im --instruction "在测试群发送消息「hello from CUA」" --show-intent
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终测试文档」，正文为「hello docs」" --show-intent
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终富文本测试」，正文为「hello docs rich」，插入标题「本周进展」和列表「完成IM扩展、调试Calendar、调试Docs」" --show-intent
python -B cli.py run --product calendar --instruction "创建一个标题为「测试会议」的日程，时间为明天10:00，参会人为李新元" --show-intent
python -B cli.py run --product vc --instruction "发起一个名为「最终测试」的视频会议，并打开摄像头和麦克风" --show-intent
```

当前支持的主要 intent：

- `im_search_only`
- `im_send_message`
- `im_send_image`
- `im_create_group`
- `im_mention_user`
- `im_search_messages`
- `im_emoji_reaction`
- `docs_open_smoke`
- `docs_create_doc`
- `docs_rich_edit`
- `docs_share_doc`
- `calendar_create_event`
- `calendar_invite_attendee`
- `calendar_modify_event_time`
- `calendar_view_busy_free`
- `vc_start_meeting`
- `vc_join_meeting`
- `vc_toggle_devices`

## Dry-run 模拟

想验证流程、规划和权限拦截，但不真实操作飞书时使用：

```powershell
$env:DRY_RUN="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="true"
$env:CUA_LARK_MODEL_PROVIDER="mock"
python -B cli.py run-suite cases\safe_smoke_suite.yaml --auto-debug
```

切回真实桌面执行：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

dry-run 的通过不代表真实飞书桌面操作通过，最终验收应以真实桌面报告为准。

## 安全开关

默认情况下，真实副作用动作会被 guard 阻止。按测试需要显式打开对应开关：

```powershell
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
$env:CUA_LARK_ALLOW_SEND_IMAGE="true"
$env:CUA_LARK_IM_TEST_IMAGE_PATH="assets\im_test_image.png"
$env:CUA_LARK_ALLOW_CREATE_GROUP="true"
$env:CUA_LARK_ALLOWED_GROUP_MEMBER="李新元"
$env:CUA_LARK_ALLOW_EMOJI_REACTION="true"

$env:CUA_LARK_ALLOW_DOC_CREATE="true"
$env:CUA_LARK_ALLOW_DOC_SHARE="true"
$env:CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT="李新元"

$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
$env:CUA_LARK_ALLOW_CALENDAR_INVITE="true"
$env:CUA_LARK_ALLOW_CALENDAR_MODIFY="true"

$env:CUA_LARK_ALLOW_VC_START="true"
$env:CUA_LARK_ALLOW_VC_JOIN="true"
$env:CUA_LARK_ALLOW_VC_DEVICE_TOGGLE="true"
$env:CUA_LARK_VC_MEETING_ID="259427455"
```

安全约束：

- IM 发送前会确认当前会话与 `CUA_LARK_ALLOWED_IM_TARGET` 一致。
- 建群成员会受 `CUA_LARK_ALLOWED_GROUP_MEMBER` 限制。
- Docs 分享对象会受 `CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT` 限制。
- Calendar 创建、邀请、修改时间分别受独立开关控制。
- VC 发起、加入、设备切换分别受独立开关控制。
- 截图不健康或模型回退 mock 时，真实点击默认会被阻止。

## 推荐全量回归顺序

先跑安全 smoke：

```powershell
python -B cli.py run-case cases\smoke_search_only.yaml --auto-debug
python -B cli.py run-case cases\im_search_only.yaml --auto-debug
python -B cli.py run-case cases\docs_open_smoke.yaml --auto-debug
python -B cli.py run-suite cases\safe_smoke_suite.yaml --auto-debug
```

再按产品跑真实 E2E：

```powershell
python -B cli.py run-suite cases\im_full_suite.yaml --auto-debug

python -B cli.py run-case cases\docs_create_doc.yaml --auto-debug
python -B cli.py run-case cases\docs_rich_edit_guarded.yaml --auto-debug
python -B cli.py run-case cases\docs_share_doc_guarded.yaml --auto-debug

python -B cli.py run-case cases\calendar_create_event.yaml --auto-debug
python -B cli.py run-case cases\calendar_invite_attendee_guarded.yaml --auto-debug
python -B cli.py run-case cases\calendar_modify_event_time_guarded.yaml --auto-debug
python -B cli.py run-case cases\calendar_view_busy_free_guarded.yaml --auto-debug

python -B cli.py run-case cases\vc_start_meeting_guarded.yaml --auto-debug
python -B cli.py run-case cases\vc_start_meeting_with_devices_guarded.yaml --auto-debug
python -B cli.py run-case cases\vc_join_meeting_guarded.yaml --auto-debug
python -B cli.py run-case cases\vc_join_meeting_no_devices_guarded.yaml --auto-debug
python -B cli.py run-case cases\vc_join_meeting_with_devices_guarded.yaml --auto-debug
python -B cli.py run-case cases\vc_toggle_devices_guarded.yaml --auto-debug
```

Docs + Calendar 组合 suite：

```powershell
python -B cli.py run-suite cases\docs_calendar_extended_suite.yaml --auto-debug
```

## 常用自然语言真实测试

IM：

```powershell
python -B cli.py run --product im --instruction "在测试群发送消息「CUA-Lark guarded smoke message」" --auto-debug
python -B cli.py run --product im --instruction "在测试群发送图片 assets\im_test_image.png" --auto-debug
python -B cli.py run --product im --instruction "创建一个群名为「CUA-Lark 测试群啦啦」的飞书测试群，成员包含李新元" --auto-debug
python -B cli.py run --product im --instruction "在测试群中@李新元发送一条测试消息" --auto-debug
python -B cli.py run --product im --instruction "在测试群中找到 hello from CUA 相关消息，并用点赞表情回复" --auto-debug
```

Docs：

```powershell
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终测试文档」，正文为「hello docs」" --auto-debug
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终富文本测试」，正文为「hello docs rich」，插入标题「本周进展」和列表「完成IM扩展、调试Calendar、调试Docs」" --auto-debug
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终分享测试」，正文为「hello docs share」，并分享给「李新元」" --auto-debug
```

Calendar：

```powershell
python -B cli.py run --product calendar --instruction "创建一个标题为「测试会议」的日程，时间为明天10:00，参会人为李新元" --auto-debug
python -B cli.py run --product calendar --instruction "创建一个标题为「邀请测试会议」的日程，时间为明天10:00，并邀请李新元参加" --auto-debug
python -B cli.py run --product calendar --instruction "把标题为「测试会议」的日程从明天10:00修改到明天11:00" --auto-debug
python -B cli.py run --product calendar --instruction "打开飞书日历，查看李新元明天 10:00 的忙闲状态，不保存日程" --auto-debug
```

VC：

```powershell
python -B cli.py run --product vc --instruction "发起一个视频会议" --auto-debug
python -B cli.py run --product vc --instruction "发起一个名为「项目例会」的视频会议" --auto-debug
python -B cli.py run --product vc --instruction "发起一个视频会议，并打开摄像头和麦克风" --auto-debug
python -B cli.py run --product vc --instruction "加入ID为259427455的会议，只打开麦克风" --auto-debug
python -B cli.py run --product vc --instruction "打开麦克风" --auto-debug
```

## 关键实现说明

主要模块：

- `intent/parser.py`：自然语言 intent 解析。
- `products/workflows.py`：产品 workflow 和步骤模板。
- `agent/nodes/plan_task.py`：规划入口和 guarded workflow 拦截。
- `agent/nodes/decide.py`：目标定位、VLM/OCR/CV 决策。
- `agent/nodes/execute.py`：执行动作、安全检查、条件动作。
- `agent/nodes/verify.py`：步骤验证。
- `agent/nodes/recover.py`：失败恢复和自愈入口。
- `tools/vision/lark_locator.py`：飞书 UI 视觉定位。
- `tools/vision/*_error_library.py`：产品错误状态库。
- `tools/desktop/executor.py`：桌面鼠标键盘执行。
- `verification/registry.py`：本地 OCR/视觉验证。
- `storage/report_writer.py`：报告输出。

关键设计：

- 坐标按当前截图和窗口动态计算，不依赖固定屏幕绝对坐标。
- 条件式清理只在检测到弹窗/浮层时执行，避免无意义点击。
- IM、Docs、Calendar、VC 的 guarded 流程相互正交，避免一个产品修复破坏其他产品。
- 真实副作用动作前后均保留截图证据和本地状态验证。
- 错误库用于识别错误页面、错误会话、弹窗残留、输入未确认、会议窗口未前台等问题。

## 报告输出

单 case 运行会生成：

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

报告记录运行模式、截图诊断、每一步 before/after 截图、坐标、输入、耗时、验证结果和失败原因。`runs/` 中的截图可能包含真实桌面内容，默认不要提交到 GitHub。

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

安全查看计划，不执行桌面动作：

```powershell
$body = @{
  task = "打开飞书日历，查看李新元明天 10:00 的忙闲状态"
  product = "calendar"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/plan `
  -ContentType "application/json" `
  -Body $body
```

## 交付状态

对照 CUA-Lark 任务要求：

- M1 单步操作：已完成。
- M2 多步流程串联和状态验证：已完成。
- M3 多产品覆盖：已覆盖 IM、Docs、Calendar、VC 四个子产品，超过至少两个子产品的要求。
- M4 评估体系：已完成结构化报告和截图证据。
- M5 进阶优化：已实现异常弹窗处理、安全 guard、错误库、自愈恢复入口、OCR/CV/VLM 混合定位。

后续交付重点不再是补核心功能，而是固定最终回归证据、整理评测报告、准备 Demo 视频和答辩材料。

## 注意事项

- 永远不要提交 `.env`。
- 永远不要提交 API Key、Authorization header、cookie、真实 token。
- 默认不要提交 `runs/` 报告截图。
- 真实 IM 发送只对测试群或测试联系人执行。
- Docs / Calendar 创建只使用无害测试标题和测试内容。
- Docs 分享只分享给明确测试联系人。
- VC 测试会真实进入会议，跑完后应退出会议，避免污染下一条用例。
- 如果截图黑屏、窗口不对或 mock 回退，不要强行真实执行。

## 更多文档

- `ACCEPTANCE.md`
- `use.md`
- `docs\system_design.md`
- `docs\evaluation.md`
- `docs\demo_script.md`
