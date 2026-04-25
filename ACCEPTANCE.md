# 验收标准

当下面检查项都通过时，可以认为当前 CUA-Lark 后端进入“可继续做真实 E2E 校准”的状态。

## 1. 环境要求

- 所有命令都在 `conda activate agent` 后执行。
- 程序能自动读取 `backend\.env`，但不会在终端、日志、报告或文档中输出 API Key。
- `python -B -c "import cli; import app.main"` 可以正常导入。

## 2. 截图与桌面诊断

```powershell
python cli.py screenshot-diagnostics --configured-only
python cli.py inspect-screen
```

通过标准：

- 能输出 monitor 信息。
- 能保存诊断截图和网格截图。
- 如果截图黑屏或纯色，报告必须明确 warning，不能把异常截图当成正常 evidence。

## 3. Mock / Dry-run 基线

```powershell
$env:CUA_LARK_MODEL_PROVIDER="mock"
$env:DRY_RUN="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="true"
python cli.py run-case cases\smoke_search_only.yaml --auto-debug
```

通过标准：

- 命令退出码为 `0`。
- 运行报告生成 `summary.json`、`summary.md`、`steps.jsonl`。
- 报告明确说明 mock/dry_run 只是模拟验证，不代表真实飞书操作成功。

## 3.1 自然语言解析基线

```powershell
python cli.py run --instruction "给测试群发送一条消息：hello from CUA" --show-intent
python cli.py run --instruction "在IM中搜索测试群，但不要发送消息" --show-intent
python cli.py run --instruction "打开云文档，不创建任何文件，只确认云文档入口可用" --show-intent
python cli.py run --instruction "在飞书云文档中新建一个测试文档，标题为「CUA Docs 自动化测试」，正文为「hello docs」" --show-intent
python cli.py run --instruction "打开飞书日历，创建一个会议，标题为「CUA Calendar 自动化测试」，时间为「明天 10:00」，参会人为「张三、李四」" --show-intent
```

通过标准：

- IM 发送应解析为 `im_send_message` 和 `im_send_message_guarded`。
- IM 搜索但不发送应解析为 `im_search_only`。
- 打开云文档但不创建文件应解析为 `docs_open_smoke`。
- 创建云文档应解析为 `docs_create_doc` 和 `docs_create_doc_guarded`，并解析出标题和正文。
- 创建日程应解析为 `calendar_create_event` 和 `calendar_create_event_guarded`，并解析出标题、时间和参会人。
- 运行报告中必须出现 `Parsed Intent`，说明解析出的目标、消息、模板和安全策略。

## 4. 真实 IM 安全烟测

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
python cli.py run-case cases\smoke_search_only.yaml --auto-debug
```

通过标准：

- `summary.md` 中 `Status=pass`。
- `Dry Run=False`，`Real Desktop Execution=True`。
- 每一步都有 before/after screenshot。
- 报告能看到点击坐标、输入文本、耗时、验证原因。
- 不发送任何聊天消息。

## 5. 双产品安全 Suite

```powershell
python cli.py run-suite cases\safe_smoke_suite.yaml --auto-debug
```

通过标准：

- suite 报告显示 IM 和 Docs 两个 product。
- 每个子 case 都生成独立报告。
- `suite_summary.md` 和 `suite_summary.json` 正常生成。

## 6. 受保护 IM 发送

默认情况下运行：

```powershell
python cli.py run-case cases\im_send_message_guarded.yaml --auto-debug
```

应当在发送保护阶段失败，而不是继续发送消息。

只有明确使用测试群或测试联系人时，才允许设置：

```powershell
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
python cli.py run-case cases\im_send_message_guarded.yaml --auto-debug
```

通过标准：

- 如果设置了 `CUA_LARK_ALLOWED_IM_TARGET`，目标必须完全一致。
- 如果 `CUA_LARK_ALLOWED_IM_TARGET` 留空，则使用自然语言解析出的目标继续执行。
- 没有安全开关时不能打开会话、输入草稿或发送。
- 安全开关开启后，也只能在测试群或测试联系人中验证。

## 7. 受保护 Docs 创建文档

默认情况下运行：

```powershell
python cli.py run-case cases\docs_create_doc.yaml --auto-debug
```

应当在创建保护阶段失败，而不是继续点击新建文档。

开启真实创建测试文档：

```powershell
$env:CUA_LARK_ALLOW_DOC_CREATE="true"
python cli.py run --instruction "在飞书云文档中新建一个测试文档，标题为「CUA Docs 自动化测试」，正文为「hello docs」" --auto-debug
```

通过标准：

- 没有 `CUA_LARK_ALLOW_DOC_CREATE=true` 时，不能执行创建文档、输入标题或输入正文。
- 开关开启后，报告里 `Allow Doc Create=True`。
- 最终截图和 VLM 验证能确认标题、正文存在。
- 不分享、不发布、不写入真实业务内容。

## 8. 受保护 Calendar 创建日程

默认情况下运行：

```powershell
python cli.py run-case cases\calendar_create_event.yaml --auto-debug
```

应当在创建保护阶段失败，而不是继续点击新建日程。

开启真实创建测试日程：

```powershell
$env:CUA_LARK_ALLOW_CALENDAR_CREATE="true"
python cli.py run --instruction "打开飞书日历，创建一个会议，标题为「CUA Calendar 自动化测试」，时间为「明天 10:00」，参会人为「张三、李四」" --auto-debug
```

通过标准：

- 没有 `CUA_LARK_ALLOW_CALENDAR_CREATE=true` 时，不能执行创建日程、填写信息或保存。
- 开关开启后，报告里 `Allow Calendar Create=True`。
- 最终截图和 VLM 验证能确认日程标题和时间存在。
- 第一次真实测试只使用无害测试标题和测试参会人。

## 7. 报告要求

每次 case 运行必须生成：

```text
runs/reports/run_YYYYMMDD_HHMMSS_xxxxxxxx/
|-- summary.json
|-- summary.md
|-- steps.jsonl
|-- screenshots/
`-- artifacts/
```

报告必须包含：

- 运行模式：model provider、dry_run、placeholder screenshot、真实桌面执行、mock verification。
- 截图诊断结果。
- 每一步动作、坐标、输入、热键、耗时、验证结果和失败原因。
- warnings 和 failure category。
