# CUA-Lark 后端

CUA-Lark 后端用于运行飞书桌面 GUI 自动化测试。它不调用飞书开放平台 API 完成业务动作，而是像真实用户一样观察截图、理解自然语言、规划步骤、操作鼠标键盘，并在每一步保存截图和报告证据。

当前重点覆盖三个飞书子产品：

- IM：文本/图片发送、创建群组、@ 提及、搜索聊天记录、表情回复。
- Docs：创建文档、编辑正文、插入标题/列表、分享文档。
- Calendar：创建日程、邀请参会人、修改日程时间、查看忙闲状态。

## 快速开始

所有项目命令建议在 `agent` conda 环境中运行：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
```

复制配置模板：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写真实模型配置。不要提交 `.env`，不要把 API Key、Authorization header、cookie 或真实 token 写入日志、报告或 README。PowerShell 中临时设置的环境变量优先级高于 `.env`。

## 当前真实验证进展

更新时间：2026-04-30 19:09。状态口径以 `runs\reports` 中最近真实报告为准；如果最近回归失败，同时保留“最后已知通过报告”作为能力证据。

IM 最新真实回归已全部通过：

- 发送文本消息：`cases\im_send_message_guarded.yaml`，最新通过 `runs\reports\run_20260426_173819_7c6c0263`，7/7 步通过。
- 发送图片消息：`cases\im_send_image_guarded.yaml`，最新通过 `runs\reports\run_20260426_174305_4aaa8145`，7/7 步通过。
- 创建群组：`cases\im_create_group_guarded.yaml`，最新通过 `runs\reports\run_20260426_183354_ac0c06f0`，10/10 步通过。
- @ 提及：`cases\im_mention_user_guarded.yaml`，最新通过 `runs\reports\run_20260426_180101_f8712542`，9/9 步通过。
- 搜索消息记录：`cases\im_search_messages.yaml`，最新通过 `runs\reports\run_20260426_174845_c9d4c0b4`，6/6 步通过。
- 表情回复：`cases\im_emoji_reaction_guarded.yaml`，最新通过 `runs\reports\run_20260426_184529_54dfb4ac`，9/10 步通过，1 步条件跳过。

Docs 最新真实回归状态：

- 创建文档：`cases\docs_create_doc.yaml`，最新通过 `runs\reports\run_20260430_185053_44f5eb5f`，12/15 步通过，3 步条件跳过。
- 编辑文本内容 / 插入标题和列表：`cases\docs_rich_edit_guarded.yaml`，最新通过 `runs\reports\run_20260430_190149_573da0e8`，14/17 步通过，3 步条件跳过。
- 分享文档：`cases\docs_share_doc_guarded.yaml`，最新通过 `runs\reports\run_20260430_190926_55597bc7`，21/24 步通过，3 步条件跳过。

Calendar 最新真实回归状态：

- 创建日程：`cases\calendar_create_event.yaml`，最近一轮失败 `runs\reports\run_20260426_165223_0bd0a1f3`，失败点为参会人搜索结果 OCR 未确认；最后已知通过报告为 `runs\reports\run_20260426_110901_06bdf40b`。
- 邀请参会人：`cases\calendar_invite_attendee_guarded.yaml`，最近一轮失败 `runs\reports\run_20260426_165410_4c3ec35b`，失败点为参会人搜索结果 OCR 未确认；最后已知通过报告为 `runs\reports\run_20260426_130145_6805e8ae`。
- 修改日程时间：`cases\calendar_modify_event_time_guarded.yaml`，最近一轮失败 `runs\reports\run_20260426_165551_430bb4be`，失败点为最终 OCR 未找到日程标题且修改后时间未命中；最后已知通过报告为 `runs\reports\run_20260426_120155_ad2c1bea`。
- 查看忙闲状态：`cases\calendar_view_busy_free_guarded.yaml`，最近一轮失败 `runs\reports\run_20260426_165749_76613279`，失败点为 2026-04-27 10:00 附近未看到李新元忙闲条目；最后已知通过报告为 `runs\reports\run_20260426_152523_2aec6992`。

这些用例都保留了安全开关。涉及真实写入、发送、分享、建群、改日程的动作默认会被拦截，只有显式设置对应环境变量后才会执行。

## 推荐调试顺序

先确认截图链路健康：

```powershell
python cli.py screenshot-diagnostics --configured-only
python cli.py inspect-screen
```

再运行安全 smoke，不发送、不创建：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
python -B cli.py run-case cases\smoke_search_only.yaml --auto-debug
python -B cli.py run-case cases\docs_open_smoke.yaml --auto-debug
```

然后运行 mock/dry-run suite：

```powershell
$env:CUA_LARK_MODEL_PROVIDER="mock"
$env:DRY_RUN="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="true"
python -B cli.py run-suite cases\safe_smoke_suite.yaml --auto-debug
python -B cli.py run-suite cases\docs_calendar_extended_suite.yaml --auto-debug
```

最后再打开真实安全开关跑 E2E。

## Docs 用法

Docs 创建文档：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
python -B cli.py run-case cases\docs_create_doc.yaml --auto-debug
```

Docs 富文本编辑，包含标题和列表：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
python -B cli.py run-case cases\docs_rich_edit_guarded.yaml --auto-debug
```

Docs 分享文档给测试联系人：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
$env:CUA_LARK_ALLOW_DOC_SHARE="true"
$env:CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT="李新元"
python -B cli.py run-case cases\docs_share_doc_guarded.yaml --auto-debug
```

Docs 当前流程要点：

- 进入云文档后 hover “新建”，等待菜单自动展开。
- OCR 点击“文档”，再点击空白文档卡片中间的加号。
- 新文档在浏览器编辑器打开后保持浏览器前台，不再强行切回飞书桌面端。
- 弹层处理使用条件式 `Esc` 或条件式点击，只有视觉条件存在时才执行。
- 分享链路使用分享按钮、收件人输入框、搜索结果、添加按钮、最终确认按钮的 OCR/像素定位。

## Calendar 用法

Calendar 创建日程：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
python -B cli.py run-case cases\calendar_create_event.yaml --auto-debug
```

Calendar 创建日程并邀请参会人：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
$env:CUA_LARK_ALLOW_CALENDAR_INVITE="true"
python -B cli.py run-case cases\calendar_invite_attendee_guarded.yaml --auto-debug
```

Calendar 创建日程并修改时间：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
$env:CUA_LARK_ALLOW_CALENDAR_MODIFY="true"
python -B cli.py run-case cases\calendar_modify_event_time_guarded.yaml --auto-debug
```

Calendar 查看联系人忙闲状态，不保存日程：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
python -B cli.py run-case cases\calendar_view_busy_free_guarded.yaml --auto-debug
```

Calendar 当前流程要点：

- 创建日程会先条件式清理旧编辑器、确认弹窗、添加参会人弹窗和会议室侧栏。
- 日期选择使用 OCR 识别日期选择器标题和 7 列日期网格，再根据目标日期计算格子中心，避免误点到相邻月份。
- 参会人选择使用 OCR 搜索结果行定位。
- 忙闲状态查看会搜索联系人并订阅/选择其日历；右侧搜索结果图标用像素状态判断，灰色图标才点击，蓝色已选中图标会跳过，避免重复点击导致退订。
- 忙闲验证只检查右侧主时间轴区域，要求联系人/自身/时间轴/日历网格/绿色忙闲标记等证据组合成立，避免把左侧搜索结果或右侧聊天窗口误判成忙闲结果。

## IM 用法

IM 基线发送文本仍使用 guarded 流程：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
python -B cli.py run-case cases\im_send_message_guarded.yaml --auto-debug
```

扩展 IM 用例：

- `cases\im_send_image_guarded.yaml`：发送图片，最新真实通过；需要 `CUA_LARK_ALLOW_SEND_IMAGE=true`，并设置 `CUA_LARK_IM_TEST_IMAGE_PATH` 或使用默认测试图片。
- `cases\im_create_group_guarded.yaml`：创建群组，最新真实通过；需要 `CUA_LARK_ALLOW_CREATE_GROUP=true`，建议设置 `CUA_LARK_ALLOWED_GROUP_MEMBER=李新元`。
- `cases\im_mention_user_guarded.yaml`：@ 提及并发送，最新真实通过；需要 `CUA_LARK_ALLOW_SEND_MESSAGE=true`。
- `cases\im_search_messages.yaml`：搜索聊天记录，最新真实通过；默认不需要发送开关。
- `cases\im_emoji_reaction_guarded.yaml`：表情回复，最新真实通过；需要 `CUA_LARK_ALLOW_EMOJI_REACTION=true`。
- `cases\im_full_suite.yaml`：IM 扩展 suite，包含上述 6 个能力和安全搜索 smoke。

IM 当前关键保护：

- 搜索结果必须 OCR 确认目标行，避免把“测试群”点成知识问答或其他会话。
- 打开测试群后，发送、图片、@、表情等危险动作会先检查当前右侧会话是否仍是允许目标。
- 已加入 IM 错误操作参考库，用于识别“搜索结果未进入目标群”“进入私聊”“菜单/弹窗残留”等错误状态。
- 建群流程对飞书白屏加载弹窗做了有界等待，成员输入框和群名输入框均使用 OCR 定位。
- 表情回复先 OCR 找到目标消息行，再只在目标消息附近寻找快捷表情按钮，避免点到标题栏图标。

## 自然语言路由

CLI 会先把自然语言解析成结构化意图，再选择产品 workflow：

```powershell
python -B cli.py run --instruction "在飞书云文档中新建一个测试文档，标题为「CUA Docs 自动化测试」，正文为「hello docs」" --show-intent
python -B cli.py run --instruction "打开飞书日历，查看李新元明天 10:00 的忙闲状态" --show-intent
```

当前已支持的相关意图包括：

- `im_send_message`
- `im_send_image`
- `im_create_group`
- `im_mention_user`
- `im_search_messages`
- `im_emoji_reaction`
- `docs_create_doc`
- `docs_rich_edit`
- `docs_share_doc`
- `calendar_create_event`
- `calendar_invite_attendee`
- `calendar_modify_event_time`
- `calendar_view_busy_free`

## 安全开关

- `DRY_RUN=true`：只验证流程和报告，不真实操作桌面。
- `CUA_LARK_PLACEHOLDER_SCREENSHOT=true`：允许 dry-run 下生成占位截图。
- `DRY_RUN=false`：真实桌面执行，运行前会做截图健康检查。
- `CUA_LARK_ALLOW_UNHEALTHY_SCREENSHOT=false`：截图疑似黑屏或纯色时默认阻止真实执行。
- `CUA_LARK_ALLOW_MOCK_REAL_EXECUTION=false`：真实执行时如果模型 provider 退回 mock，默认阻止点击。
- `CUA_LARK_AUTO_DEBUG=true` 或 `--auto-debug`：自动调试执行，异常即停。
- `CUA_LARK_ABORT_FILE=./runs/ABORT`：创建该文件可在下一步动作前中断运行。
- `CUA_LARK_ALLOW_SEND_MESSAGE=true`：允许真实发送 IM 文本或 @ 提及消息。
- `CUA_LARK_ALLOWED_IM_TARGET=测试群`：限制真实 IM 发送目标。
- `CUA_LARK_ALLOW_SEND_IMAGE=true`：允许真实发送图片。
- `CUA_LARK_ALLOW_CREATE_GROUP=true`：允许真实创建群组。
- `CUA_LARK_ALLOWED_GROUP_MEMBER=李新元`：限制创建群组时允许添加的成员。
- `CUA_LARK_ALLOW_EMOJI_REACTION=true`：允许真实表情回复。
- `CUA_LARK_ALLOW_DOC_CREATE=true`：允许真实创建/编辑测试云文档。
- `CUA_LARK_ALLOW_DOC_SHARE=true`：允许真实分享文档。
- `CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT=李新元`：限制 Docs 分享对象。
- `CUA_LARK_ALLOW_CALENDAR_CREATE=true`：允许真实创建测试日程。
- `CUA_LARK_ALLOW_CALENDAR_INVITE=true`：允许真实邀请参会人。
- `CUA_LARK_ALLOW_CALENDAR_MODIFY=true`：允许真实修改日程时间。

## 当前示例用例

- `cases\smoke_search_only.yaml`：IM 搜索框安全 smoke，不发送消息。
- `cases\im_search_only.yaml`：IM 搜索目标安全用例，不进入会话，不发送消息。
- `cases\im_send_message_guarded.yaml`：受保护 IM 文本发送。
- `cases\im_send_image_guarded.yaml`：受保护 IM 图片发送。
- `cases\im_create_group_guarded.yaml`：受保护创建群组。
- `cases\im_mention_user_guarded.yaml`：受保护 @ 提及。
- `cases\im_search_messages.yaml`：搜索聊天记录。
- `cases\im_emoji_reaction_guarded.yaml`：受保护表情回复。
- `cases\im_full_suite.yaml`：IM 扩展 suite。
- `cases\docs_open_smoke.yaml`：云文档入口安全 smoke，不创建、不编辑文档。
- `cases\docs_create_doc.yaml`：受保护 Docs 创建测试文档。
- `cases\docs_rich_edit_guarded.yaml`：受保护 Docs 标题/列表编辑。
- `cases\docs_share_doc_guarded.yaml`：受保护 Docs 分享。
- `cases\calendar_create_event.yaml`：受保护 Calendar 创建测试日程。
- `cases\calendar_invite_attendee_guarded.yaml`：受保护 Calendar 邀请参会人。
- `cases\calendar_modify_event_time_guarded.yaml`：受保护 Calendar 修改时间。
- `cases\calendar_view_busy_free_guarded.yaml`：Calendar 忙闲状态查看，不保存日程。
- `cases\safe_smoke_suite.yaml`：IM + Docs 安全 suite。
- `cases\docs_calendar_extended_suite.yaml`：Docs + Calendar 扩展 suite。

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

已知待补齐项：当前报告 Runtime Mode 已打印 Doc Create、Calendar Create、Calendar Invite 等开关，但还没有完整打印 `CUA_LARK_ALLOW_DOC_SHARE`、`CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT` 和 `CUA_LARK_ALLOW_CALENDAR_MODIFY`，后续应补到 `RuntimeContext` 与 `report_writer`。

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

## 更多文档

- `ACCEPTANCE.md`
- `docs\system_design.md`
- `docs\evaluation.md`
- `docs\demo_script.md`
