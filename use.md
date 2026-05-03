# CUA-Lark 使用命令

本文档按运行风险分组。运行前先确认你要做的是：

- **设备/截图校验**：只检查环境、截图、屏幕坐标，不执行业务流程。
- **解析校验**：只看自然语言会被解析成什么，不点击桌面。
- **Dry-run 模拟**：跑流程但不真实点击飞书桌面。
- **真实安全测试**：真实点击飞书桌面，但不发送、不创建、不保存、不加入会议。
- **真实业务操作**：会发送消息、发图片、建群、创建/分享文档、创建/修改日程、发起/加入会议或切换摄像头/麦克风。

## 0. 基础环境

每次打开新 PowerShell 后先执行：

```powershell
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"
conda activate agent
cd path\to\feishu_cua_agent
```

真实桌面执行的基础配置：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

如果真实模型未配置好，系统会因为 `effective_model_provider=mock` 阻止真实点击。除非明确接受风险，不要设置 `CUA_LARK_ALLOW_MOCK_REAL_EXECUTION=true`。

## 1. 设备/截图校验

这类命令不属于业务测试，只用来确认 Agent 能看到正确屏幕。

```powershell
python cli.py screenshot-diagnostics --configured-only
python cli.py inspect-screen
```

用途：

- `screenshot-diagnostics --configured-only`：检查当前配置的显示器是否能正常截图。
- `inspect-screen`：生成带坐标网格的截图，人工确认飞书是否在 Agent 可见屏幕中。

如果截图异常，先修复显示器、远程桌面、锁屏、飞书窗口位置等问题，再跑任何真实测试。

## 2. 解析校验，不执行

自然语言 CLI 可以先用 `--show-intent` 看解析结果。这不会点击桌面，也不会执行任何动作。

```powershell
python -B cli.py run --product im --instruction "在测试群发送消息「hello from CUA」" --show-intent
python -B cli.py run --product docs --instruction "新建一个标题为「测试文档」的云文档，正文为「hello docs」" --show-intent
python -B cli.py run --product calendar --instruction "创建一个标题为「测试会议」的日程，时间为明天10:00，参会人为李新元" --show-intent
python -B cli.py run --product vc --instruction "发起一个名为「最终测试」的视频会议，并打开摄像头和麦克风" --show-intent
```

## 3. Dry-run 模拟，不真实点击

想验证流程、规划和权限拦截，但不真实操作飞书时使用：

```powershell
$env:DRY_RUN="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="true"
$env:CUA_LARK_MODEL_PROVIDER="mock"
```

然后运行任意 `run-case`、`run-suite` 或 `run` 命令。注意：dry-run 的通过不代表真实飞书桌面操作通过。

切回真实桌面执行：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
```

## 4. 真实安全测试配置

真实安全测试会点击飞书，但不应该产生发送、创建、保存、会议等副作用。建议先关闭所有真实业务开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"

$env:CUA_LARK_ALLOW_SEND_MESSAGE="false"
$env:CUA_LARK_ALLOW_SEND_IMAGE="false"
$env:CUA_LARK_ALLOW_CREATE_GROUP="false"
$env:CUA_LARK_ALLOW_EMOJI_REACTION="false"
$env:CUA_LARK_ALLOW_DOC_CREATE="false"
$env:CUA_LARK_ALLOW_DOC_SHARE="false"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="false"
$env:CUA_LARK_ALLOW_CALENDAR_INVITE="false"
$env:CUA_LARK_ALLOW_CALENDAR_MODIFY="false"
$env:CUA_LARK_ALLOW_VC_START="false"
$env:CUA_LARK_ALLOW_VC_JOIN="false"
$env:CUA_LARK_ALLOW_VC_DEVICE_TOGGLE="false"
```

安全 YAML 用例：

```powershell
python -B cli.py run-case cases\smoke_search_only.yaml --auto-debug
python -B cli.py run-case cases\im_search_only.yaml --auto-debug
python -B cli.py run-case cases\im_search_messages.yaml --auto-debug
python -B cli.py run-case cases\docs_open_smoke.yaml --auto-debug
python -B cli.py run-case cases\calendar_view_busy_free_guarded.yaml --auto-debug
```

安全 Suite：

```powershell
python -B cli.py run-suite cases\safe_smoke_suite.yaml --auto-debug
```

安全自然语言 CLI：

```powershell
python -B cli.py run --product im --instruction "在飞书IM中搜索「测试群」，不要发送消息" --auto-debug
python -B cli.py run --product im --instruction "在飞书IM中搜索聊天记录「hello from CUA」，不发送任何消息" --auto-debug
python -B cli.py run --product docs --instruction "打开飞书云文档入口，只观察页面，不创建文档" --auto-debug
python -B cli.py run --product calendar --instruction "打开飞书日历，查看「李新元」明天 10:00 的忙闲状态，不保存日程" --auto-debug
```

## 5. 用例之间清理飞书浮窗

多个真实用例连续运行时，上一个用例可能留下搜索浮窗、菜单、表情面板、群创建弹窗等状态。建议每个真实用例前先清理并把飞书置于前台：

```powershell
python -c "import time, pyautogui; from tools.desktop.window_manager import WindowManager; wm=WindowManager(); wm.focus_lark(); time.sleep(0.3); [pyautogui.press('esc') or time.sleep(0.2) for _ in range(4)]; wm.focus_lark(); time.sleep(0.3); print('active=' + wm.get_active_window_title())"
```

推荐执行方式：

```powershell
# 先清理
python -c "import time, pyautogui; from tools.desktop.window_manager import WindowManager; wm=WindowManager(); wm.focus_lark(); time.sleep(0.3); [pyautogui.press('esc') or time.sleep(0.2) for _ in range(4)]; wm.focus_lark(); time.sleep(0.3); print('active=' + wm.get_active_window_title())"

# 再跑单个用例
python -B cli.py run-case cases\im_search_only.yaml --auto-debug
```

不要直接长时间跑混合 suite 来定位问题。定位阶段优先一个一个跑，并记录每个用例的 `report_dir`、`summary_md` 和 pass/fail。

## 6. IM 真实业务操作

### 6.1 IM 发文本消息

副作用：向指定会话发送文本消息。

运行前开关：

```powershell
$env:DRY_RUN="false"
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

### 6.2 IM 发图片

副作用：向指定会话发送图片。

运行前开关：

```powershell
$env:DRY_RUN="false"
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

### 6.3 IM 创建群

副作用：创建真实群组。

运行前开关：

```powershell
$env:DRY_RUN="false"
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

### 6.4 IM @ 提及并发送

副作用：向指定会话发送包含 @ 的消息。

运行前开关：

```powershell
$env:DRY_RUN="false"
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

### 6.5 IM 点赞表情回复

副作用：对指定会话里的消息添加表情回复。

运行前开关：

```powershell
$env:DRY_RUN="false"
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

### 6.6 IM 完整 Suite

`im_full_suite.yaml` 是混合 suite，包含安全搜索和真实业务操作。运行前需要打开所有 IM 相关开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
$env:CUA_LARK_ALLOW_SEND_IMAGE="true"
$env:CUA_LARK_IM_TEST_IMAGE_PATH="assets\im_test_image.png"
$env:CUA_LARK_ALLOW_CREATE_GROUP="true"
$env:CUA_LARK_ALLOWED_GROUP_MEMBER="李新元"
$env:CUA_LARK_ALLOW_EMOJI_REACTION="true"
```

运行：

```powershell
python -B cli.py run-suite cases\im_full_suite.yaml --auto-debug
```

定位问题时不建议先跑完整 suite，建议按顺序单个跑：

```powershell
python -B cli.py run-case cases\im_search_only.yaml --auto-debug
python -B cli.py run-case cases\im_search_messages.yaml --auto-debug
python -B cli.py run-case cases\im_send_message_guarded.yaml --auto-debug
python -B cli.py run-case cases\im_send_image_guarded.yaml --auto-debug
python -B cli.py run-case cases\im_mention_user_guarded.yaml --auto-debug
python -B cli.py run-case cases\im_emoji_reaction_guarded.yaml --auto-debug
python -B cli.py run-case cases\im_create_group_guarded.yaml --auto-debug
```

## 7. Docs 真实业务操作

### 7.1 创建文档

副作用：创建真实云文档。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
python -B cli.py run-case cases\docs_create_doc.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终测试文档」，正文为「hello docs」" --auto-debug
```

### 7.2 创建文档并写富文本

副作用：创建真实云文档并编辑内容。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
python -B cli.py run-case cases\docs_rich_edit_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终富文本测试」，正文为「hello docs rich」，插入标题「本周进展」和列表「完成IM扩展、调试Calendar、调试Docs」" --auto-debug
```

### 7.3 创建并分享文档

副作用：创建真实云文档，并分享给指定人员。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
$env:CUA_LARK_ALLOW_DOC_SHARE="true"
$env:CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT="李新元"
python -B cli.py run-case cases\docs_share_doc_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product docs --instruction "在飞书云文档中新建一个测试文档，标题为「最终分享测试」，正文为「hello docs share」，并分享给「李新元」" --auto-debug
```

## 8. Calendar 真实业务操作

### 8.1 创建日程

副作用：创建真实日程。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
python -B cli.py run-case cases\calendar_create_event.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product calendar --instruction "打开飞书日历，创建一个测试日程，标题为「最终测试会议」，时间为「明天 10:00」，参会人为「李新元」" --auto-debug
```

### 8.2 创建日程并邀请参会人

副作用：创建真实日程，并邀请参会人。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
$env:CUA_LARK_ALLOW_CALENDAR_INVITE="true"
python -B cli.py run-case cases\calendar_invite_attendee_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product calendar --instruction "打开飞书日历，创建一个测试日程，标题为「最终邀请测试」，时间为「明天 10:00」，邀请参会人「李新元」" --auto-debug
```

### 8.3 创建日程并修改时间

副作用：创建真实日程，并修改时间。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
$env:CUA_LARK_ALLOW_CALENDAR_MODIFY="true"
python -B cli.py run-case cases\calendar_modify_event_time_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product calendar --instruction "打开飞书日历，创建一个测试日程，标题为「最终改时间测试」，时间为「明天 10:00」，然后把时间修改为「明天 11:00」" --auto-debug
```

## 9. VC 真实业务操作

VC 用例都属于真实业务操作或真实设备状态操作。运行前确认摄像头、麦克风、会议权限和测试会议 ID。

### 9.1 发起会议

副作用：发起真实会议。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_VC_START="true"
python -B cli.py run-case cases\vc_start_meeting_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "发起一个视频会议" --auto-debug
python -B cli.py run --product vc --instruction "发起一个名为「最终测试」的视频会议" --auto-debug
```

### 9.2 发起会议并设置摄像头/麦克风

副作用：发起真实会议，并切换摄像头/麦克风状态。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_VC_START="true"
$env:CUA_LARK_ALLOW_VC_DEVICE_TOGGLE="true"
python -B cli.py run-case cases\vc_start_meeting_with_devices_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "发起一个视频会议，并打开摄像头和麦克风" --auto-debug
python -B cli.py run --product vc --instruction "发起一个视频会议，只打开摄像头" --auto-debug
python -B cli.py run --product vc --instruction "发起一个视频会议，只打开麦克风" --auto-debug
python -B cli.py run --product vc --instruction "发起一个视频会议，并关闭摄像头和麦克风" --auto-debug
python -B cli.py run --product vc --instruction "发起一个名为「最终测试」的视频会议，并打开摄像头和麦克风" --auto-debug
python -B cli.py run --product vc --instruction "发起一个名为「最终测试」的视频会议，只打开麦克风" --auto-debug
```

### 9.3 加入会议

副作用：加入真实会议。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_VC_JOIN="true"
$env:CUA_LARK_VC_MEETING_ID="259427455"
python -B cli.py run-case cases\vc_join_meeting_guarded.yaml --auto-debug
python -B cli.py run-case cases\vc_join_meeting_no_devices_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "加入ID为259427455的会议" --auto-debug
```

### 9.4 加入会议并设置摄像头/麦克风

副作用：加入真实会议，并切换摄像头/麦克风状态。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_VC_JOIN="true"
$env:CUA_LARK_ALLOW_VC_DEVICE_TOGGLE="true"
$env:CUA_LARK_VC_MEETING_ID="259427455"
python -B cli.py run-case cases\vc_join_meeting_with_devices_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "加入ID为259427455的会议，并打开摄像头和麦克风" --auto-debug
python -B cli.py run --product vc --instruction "加入ID为259427455的会议，只打开摄像头" --auto-debug
python -B cli.py run --product vc --instruction "加入ID为259427455的会议，只打开麦克风" --auto-debug
python -B cli.py run --product vc --instruction "加入ID为259427455的会议，并关闭摄像头和麦克风" --auto-debug
```

### 9.5 已在会议中切换摄像头/麦克风

副作用：修改当前会议中的设备状态。

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_VC_DEVICE_TOGGLE="true"
python -B cli.py run-case cases\vc_toggle_devices_guarded.yaml --auto-debug
```

自然语言：

```powershell
python -B cli.py run --product vc --instruction "打开摄像头和麦克风" --auto-debug
python -B cli.py run --product vc --instruction "打开摄像头" --auto-debug
python -B cli.py run --product vc --instruction "打开麦克风" --auto-debug
python -B cli.py run --product vc --instruction "关闭摄像头" --auto-debug
python -B cli.py run --product vc --instruction "关闭麦克风" --auto-debug
python -B cli.py run --product vc --instruction "关闭摄像头和麦克风" --auto-debug
```

## 10. Docs + Calendar 混合 Suite

`docs_calendar_extended_suite.yaml` 是混合 suite，包含真实创建/分享/日程修改和安全忙闲查看。运行前需要打开对应开关：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
$env:CUA_LARK_ALLOW_DOC_SHARE="true"
$env:CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT="李新元"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
$env:CUA_LARK_ALLOW_CALENDAR_INVITE="true"
$env:CUA_LARK_ALLOW_CALENDAR_MODIFY="true"
python -B cli.py run-suite cases\docs_calendar_extended_suite.yaml --auto-debug
```

定位问题时建议逐个跑，不建议直接从 suite 开始。

## 11. 模式转换速查

把任何命令改成只解析：

```powershell
# 仅限自然语言 run 命令
python -B cli.py run --product im --instruction "..." --show-intent
```

把任何真实测试改成 dry-run：

```powershell
$env:DRY_RUN="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="true"
$env:CUA_LARK_MODEL_PROVIDER="mock"
```

把 dry-run 切回真实安全测试：

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:CUA_LARK_ALLOW_SEND_MESSAGE="false"
$env:CUA_LARK_ALLOW_SEND_IMAGE="false"
$env:CUA_LARK_ALLOW_CREATE_GROUP="false"
$env:CUA_LARK_ALLOW_EMOJI_REACTION="false"
$env:CUA_LARK_ALLOW_DOC_CREATE="false"
$env:CUA_LARK_ALLOW_DOC_SHARE="false"
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="false"
$env:CUA_LARK_ALLOW_CALENDAR_INVITE="false"
$env:CUA_LARK_ALLOW_CALENDAR_MODIFY="false"
$env:CUA_LARK_ALLOW_VC_START="false"
$env:CUA_LARK_ALLOW_VC_JOIN="false"
$env:CUA_LARK_ALLOW_VC_DEVICE_TOGGLE="false"
```

把真实安全测试切到某个真实业务操作：

```powershell
# 只打开当前要测的那一个或几个开关，不要一次打开全部。
# 例：IM 发文本
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
python -B cli.py run-case cases\im_send_message_guarded.yaml --auto-debug
```

## 12. 报告位置

每个用例结束后终端会输出：

- `report_dir`
- `summary_json`
- `summary_md`

记录结果时优先记录 `summary_md`，例如：

```text
runs\reports\run_YYYYMMDD_HHMMSS_xxxxxxxx\summary.md
```

Suite 报告位置：

```text
runs\reports\suite_YYYYMMDD_HHMMSS_xxxxxxxx\suite_summary.md
```
