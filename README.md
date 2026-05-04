# CUA-Lark Backend

CUA-Lark Backend 是一个面向飞书桌面端的 Computer-Use Agent 测试框架。项目不通过飞书开放平台 API 完成业务动作，而是模拟真实用户在桌面端进行观察、定位、点击、输入、验证和报告生成。

当前项目覆盖 IM、Docs、Calendar、VC 四个飞书子产品，支持 YAML 用例、Suite 批量用例和自然语言 CLI 三种运行方式。所有核心功能用例已经完成真实桌面回归测试。

## 1. 功能范围

| 产品 | 已覆盖能力 |
| --- | --- |
| IM | 搜索会话、搜索聊天记录、发送文本、发送图片、创建群、@ 提及成员、对指定消息添加点赞表情 |
| Docs | 打开云文档入口、新建文档、填写标题和正文、富文本标题/列表编辑、分享文档 |
| Calendar | 创建日程、邀请参会人、修改日程时间、查看忙闲状态 |
| VC | 发起会议、发起命名会议、加入指定会议、加入/发起后控制摄像头和麦克风、会中切换设备 |

## 2. 核心模块

| 模块 | 作用 |
| --- | --- |
| `cli.py` | 命令行入口，支持 `run`、`run-case`、`run-suite`、截图诊断等命令 |
| `intent/parser.py` | 自然语言指令解析，生成结构化 intent |
| `products/workflows.py` | IM / Docs / Calendar / VC 的工作流模板 |
| `agent/graph.py` | Agent 执行图编排 |
| `agent/nodes/` | 任务解析、规划、感知、执行、恢复、报告等节点 |
| `tools/desktop/` | 桌面窗口聚焦、鼠标键盘执行 |
| `tools/vision/` | OCR、视觉定位、错误库、截图状态识别 |
| `verification/registry.py` | 执行后验证规则 |
| `storage/` | 运行日志和报告输出 |
| `cases/` | YAML 测试用例和 Suite |

## 3. 环境准备

每次打开新的 PowerShell 后，先进入项目根目录并激活环境：

```powershell
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"
conda activate agent
cd path\to\feishu_cua_agent
```

首次运行前复制配置模板：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写模型相关配置。PowerShell 中临时设置的环境变量优先级高于 `.env`。

真实桌面运行的基础开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

如果只想检查解析结果，不执行桌面动作，使用 `--show-intent`：

```powershell
python -B cli.py run --product im --instruction "在测试群发送消息「hello from CUA」" --show-intent
```

如果只想 dry-run，不真实点击飞书桌面：

```powershell
$env:DRY_RUN="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="true"
$env:CUA_LARK_MODEL_PROVIDER="mock"
```

## 4. 运行命令格式

所有任务都使用统一的三类入口。

运行单个 YAML 用例：

```powershell
python -B cli.py run-case cases\<case_name>.yaml --auto-debug
```

运行 YAML Suite：

```powershell
python -B cli.py run-suite cases\<suite_name>.yaml --auto-debug
```

运行自然语言任务：

```powershell
python -B cli.py run --product <im|docs|calendar|vc> --instruction "<自然语言任务>" --auto-debug
```

设备和截图校验命令：

```powershell
python cli.py screenshot-diagnostics --configured-only
python cli.py inspect-screen
```

## 5. IM 用例

### 5.1 安全搜索 Smoke

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

YAML：

```powershell
python -B cli.py run-case cases\smoke_search_only.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product im --instruction "安全烟测：打开或聚焦飞书 IM，定位搜索框，输入 harmless-smoke-test，不发送任何聊天消息" --auto-debug
```

### 5.2 搜索会话

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

YAML：

```powershell
python -B cli.py run-case cases\im_search_only.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product im --instruction "在飞书 IM 中搜索「测试群」，不要发送消息" --auto-debug
```

### 5.3 搜索聊天记录

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

YAML：

```powershell
python -B cli.py run-case cases\im_search_messages.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product im --instruction "在飞书 IM 中搜索聊天记录「hello from CUA」，不发送任何消息" --auto-debug
```

### 5.4 发送文本消息

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
```

YAML：

```powershell
python -B cli.py run-case cases\im_send_message_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product im --instruction "在测试群发送消息「CUA-Lark guarded smoke message」" --auto-debug
```

### 5.5 发送图片消息

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_SEND_IMAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
$env:CUA_LARK_IM_TEST_IMAGE_PATH="assets\im_test_image.png"
```

YAML：

```powershell
python -B cli.py run-case cases\im_send_image_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product im --instruction "在测试群发送图片 assets\im_test_image.png" --auto-debug
```

### 5.6 创建群

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_CREATE_GROUP="true"
$env:CUA_LARK_ALLOWED_GROUP_MEMBER="李新元"
```

YAML：

```powershell
python -B cli.py run-case cases\im_create_group_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product im --instruction "创建一个群名为「CUA-Lark 测试群」的飞书测试群，成员包含李新元" --auto-debug
```

### 5.7 @ 提及成员并发送消息

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
```

YAML：

```powershell
python -B cli.py run-case cases\im_mention_user_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product im --instruction "在测试群中 @李新元 发送 hello from CUA" --auto-debug
```

### 5.8 点赞表情回复

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_EMOJI_REACTION="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
```

YAML：

```powershell
python -B cli.py run-case cases\im_emoji_reaction_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product im --instruction "在测试群中找到 hello from CUA 相关消息，并用点赞表情回复" --auto-debug
```

### 5.9 IM Suite

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
$env:CUA_LARK_ALLOW_SEND_IMAGE="true"
$env:CUA_LARK_IM_TEST_IMAGE_PATH="assets\im_test_image.png"
$env:CUA_LARK_ALLOW_CREATE_GROUP="true"
$env:CUA_LARK_ALLOWED_GROUP_MEMBER="李新元"
$env:CUA_LARK_ALLOW_EMOJI_REACTION="true"
```

Suite：

```powershell
python -B cli.py run-suite cases\im_full_suite.yaml --auto-debug
```

## 6. Docs 用例

### 6.1 打开云文档入口

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

YAML：

```powershell
python -B cli.py run-case cases\docs_open_smoke.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product docs --instruction "打开飞书云文档入口，只观察页面，不创建文档" --auto-debug
```

### 6.2 新建文档

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
```

YAML：

```powershell
python -B cli.py run-case cases\docs_create_doc.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终测试文档」，正文为「hello docs」" --auto-debug
```

### 6.3 富文本编辑

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
```

YAML：

```powershell
python -B cli.py run-case cases\docs_rich_edit_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终富文本测试」，正文为「hello docs rich」，插入标题「本周进展」和列表「完成IM扩展、调试Calendar、调试Docs」" --auto-debug
```

### 6.4 分享文档

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
$env:CUA_LARK_ALLOW_DOC_SHARE="true"
$env:CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT="李新元"
```

YAML：

```powershell
python -B cli.py run-case cases\docs_share_doc_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终分享测试」，正文为「hello docs share」，并分享给「李新元」" --auto-debug
```

## 7. Calendar 用例

### 7.1 创建日程

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
```

YAML：

```powershell
python -B cli.py run-case cases\calendar_create_event.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product calendar --instruction "创建一个标题为「测试会议」的日程，时间为明天10:00，参会人为李新元" --auto-debug
```

### 7.2 邀请参会人

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
$env:CUA_LARK_ALLOW_CALENDAR_INVITE="true"
```

YAML：

```powershell
python -B cli.py run-case cases\calendar_invite_attendee_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product calendar --instruction "创建一个标题为「邀请测试会议」的日程，时间为明天10:00，并邀请李新元参加" --auto-debug
```

### 7.3 修改日程时间

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_CALENDAR_MODIFY="true"
```

YAML：

```powershell
python -B cli.py run-case cases\calendar_modify_event_time_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product calendar --instruction "把标题为「测试会议」的日程从明天10:00修改到明天11:00" --auto-debug
```

### 7.4 查看忙闲

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

YAML：

```powershell
python -B cli.py run-case cases\calendar_view_busy_free_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product calendar --instruction "打开飞书日历，查看李新元明天 10:00 的忙闲状态，不保存日程" --auto-debug
```

## 8. VC 用例

### 8.1 发起会议

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_VC_START="true"
```

YAML：

```powershell
python -B cli.py run-case cases\vc_start_meeting_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "发起一个视频会议" --auto-debug
```

### 8.2 发起会议并设置设备

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_VC_START="true"
$env:CUA_LARK_ALLOW_VC_DEVICE_TOGGLE="true"
```

YAML：

```powershell
python -B cli.py run-case cases\vc_start_meeting_with_devices_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "发起一个视频会议，并打开摄像头和麦克风" --auto-debug
```

### 8.3 加入会议

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_VC_JOIN="true"
$env:CUA_LARK_VC_MEETING_ID="259427455"
```

YAML：

```powershell
python -B cli.py run-case cases\vc_join_meeting_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "加入ID为259427455的会议" --auto-debug
```

### 8.4 加入会议但不改设备

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_VC_JOIN="true"
$env:CUA_LARK_VC_MEETING_ID="259427455"
```

YAML：

```powershell
python -B cli.py run-case cases\vc_join_meeting_no_devices_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "加入ID为259427455的会议，不修改摄像头和麦克风状态" --auto-debug
```

### 8.5 加入会议并设置设备

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_VC_JOIN="true"
$env:CUA_LARK_ALLOW_VC_DEVICE_TOGGLE="true"
$env:CUA_LARK_VC_MEETING_ID="259427455"
```

YAML：

```powershell
python -B cli.py run-case cases\vc_join_meeting_with_devices_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "加入ID为259427455的会议，只打开麦克风" --auto-debug
```

### 8.6 会中切换设备

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_VC_DEVICE_TOGGLE="true"
```

YAML：

```powershell
python -B cli.py run-case cases\vc_toggle_devices_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "打开麦克风" --auto-debug
```

## 9. Suite 回归

### 9.1 安全 Smoke Suite

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

Suite：

```powershell
python -B cli.py run-suite cases\safe_smoke_suite.yaml --auto-debug
```

### 9.2 Docs + Calendar Suite

运行前开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
$env:CUA_LARK_ALLOW_DOC_SHARE="true"
$env:CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT="李新元"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
$env:CUA_LARK_ALLOW_CALENDAR_INVITE="true"
$env:CUA_LARK_ALLOW_CALENDAR_MODIFY="true"
```

Suite：

```powershell
python -B cli.py run-suite cases\docs_calendar_extended_suite.yaml --auto-debug
```

## 10. API 服务

启动服务：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

或：

```powershell
python start_api.py
```

常用接口：

| 接口 | 作用 |
| --- | --- |
| `GET /health` | 健康检查 |
| `POST /runs` | 创建自然语言运行任务 |
| `POST /run-case` | 创建 YAML 用例运行任务 |
| `POST /plan` | 只生成计划，不执行桌面动作 |
| `POST /observe` | 截图观察 |
| `GET /diagnostics/screenshot` | 截图诊断 |
| `GET /runs/{run_id}` | 查看运行结果 |

## 11. 报告输出

单个 case 或自然语言任务会生成：

```text
runs/reports/run_YYYYMMDD_HHMMSS_xxxxxxxx/
|-- summary.json
|-- summary.md
|-- steps.jsonl
|-- screenshots/
`-- artifacts/
```

Suite 会生成：

```text
runs/reports/suite_YYYYMMDD_HHMMSS_xxxxxxxx/
|-- suite_summary.json
`-- suite_summary.md
```

报告中包含运行模式、每步动作、截图路径、定位信息、验证结果、失败原因和诊断信息。
