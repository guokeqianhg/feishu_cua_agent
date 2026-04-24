# CUA-Lark 后端

这是 CUA-Lark 智能测试 Agent 的后端实现，当前采用方案 A：

- 使用 Python 作为主运行时。
- 使用 FastAPI 提供服务接口。
- 使用 LangGraph 编排 Agent 执行流程。
- 使用 MSS/Pillow 进行截图采集，并提供本地占位截图兜底。
- 使用 PyAutoGUI/Pyperclip 执行桌面鼠标键盘操作。
- 使用 OpenAI-compatible LLM/VLM 适配层，并提供确定性的 Mock Provider。
- 每次运行都会输出结构化 JSON 报告和 Markdown 报告。

## 本地运行

所有命令都在 `agent` conda 环境中执行：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
```

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

## 启动 API 服务

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
$env:CUA_LARK_MODEL_PROVIDER="mock"
$env:DRY_RUN="true"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动后访问：

```text
http://127.0.0.1:8000/docs
```

## API 接口

- `GET /health`：查看服务健康状态。
- `POST /runs`：运行一条自然语言测试任务。
- `POST /run`：兼容旧接口，行为等同于 `/runs`。
- `POST /run-case`：运行 YAML 测试用例。
- `POST /plan`：只生成结构化计划，不执行操作。
- `POST /observe`：截图并返回当前屏幕观察摘要。
- `GET /runs/{run_id}`：读取已经落盘的运行报告。

## 示例请求

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

只生成计划：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/plan" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"task":"在IM中搜索「测试群」，发送一条消息「Hello World」","product":"im"}'
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

文件说明：

- `summary.json`：完整结构化运行报告，适合程序读取。
- `summary.md`：可读的 Markdown 报告，适合人工查看。
- `steps.jsonl`：逐行记录每个步骤的执行细节。
- `screenshots/`：保存每个步骤执行前后的截图证据。
- `artifacts/`：预留给后续调试文件、原始模型输出等。

## 示例用例

当前提供三个 YAML 示例：

- `cases\im_send_message.yaml`：IM 搜索群聊并发送消息。
- `cases\docs_create_doc.yaml`：创建云文档并输入标题。
- `cases\calendar_create_event.yaml`：创建日历会议。

运行方式：

```powershell
python cli.py run-case cases\im_send_message.yaml
python cli.py run-case cases\docs_create_doc.yaml
python cli.py run-case cases\calendar_create_event.yaml
```

## 真实模型模式

如果要接入 OpenAI-compatible 模型服务，可以设置：

```powershell
$env:CUA_LARK_MODEL_PROVIDER="auto"
$env:OPENAI_API_KEY="replace_me"
$env:OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:OPENAI_MODEL_TEXT="qwen-plus"
$env:OPENAI_MODEL_VISION="qwen-vl-max"
```

当前真实模型适配层已经预留并接入：

- 自然语言到结构化计划。
- 截图视觉描述。
- 目标元素定位。
- 步骤级验证。
- 最终用例验证。

如果真实模型调用失败，会回退到确定性 Mock 逻辑，保证本地开发和测试流程不中断。

## 验收标准

详细验收标准见：

```text
ACCEPTANCE.md
```

