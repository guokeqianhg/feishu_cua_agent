# 验收标准

当下面所有检查项都通过时，可以认为当前后端 MVP 已经达到“好了”的标准。

## 1. 环境要求

- 所有命令都必须在 `conda activate agent` 之后执行。
- 后端源码可以通过语法检查。
- `requirements.txt` 中声明的核心依赖可以在 `agent` conda 环境中正常导入。

推荐检查命令：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent
python -m compileall backend
```

## 2. 数据模型要求

- 运行时必须使用结构化 Pydantic 模型承载核心数据。
- 必须包含并实际使用以下模型：`TestCase`、`TestPlan`、`PlanStep`、`Observation`、`LocatedTarget`、`ActionResult`、`StepVerification`、`StepRunRecord`、`TestRunReport`。
- 运行报告必须包含用例信息、飞书子产品、自然语言指令、步骤记录、截图证据、最终状态、耗时、成功率、重试次数、失败分类。

## 3. 业务流程要求

- 自然语言任务可以转换为结构化 `TestPlan`。
- 每个执行步骤都必须采集执行前截图和执行后截图。
- 鼠标类操作必须经过定位结果 `LocatedTarget`，不能只依赖固定坐标。
- 执行器必须支持 `click`、`double_click`、`right_click`、`drag`、`scroll`、`type_text`、`hotkey`、`wait`、`verify`、`finish`。
- 每个步骤必须记录步骤级验证结果。
- 整个用例结束后必须记录最终验证结果。
- 失败步骤必须能按照 `retry_limit` 进行重试。

## 4. API 要求

- `GET /health` 可以返回服务健康状态。
- `POST /runs` 可以运行一条自然语言测试任务。
- `POST /run` 作为兼容旧接口的别名，行为等同于 `/runs`。
- `POST /run-case` 可以运行 YAML 测试用例。
- `POST /plan` 可以只生成结构化 `TestPlan`，不执行操作。
- `POST /observe` 可以截图并返回观察摘要。
- `GET /runs/{run_id}` 可以读取已经落盘的运行报告。

## 5. 运行产物要求

每次运行都必须创建如下目录：

```text
runs/reports/run_YYYYMMDD_HHMMSS_xxxxxxxx/
|-- summary.json
|-- summary.md
|-- steps.jsonl
|-- screenshots/
`-- artifacts/
```

产物要求：

- `summary.json` 必须是完整结构化报告。
- `summary.md` 必须是可读的 Markdown 报告。
- `steps.jsonl` 必须逐行记录步骤执行信息。
- `screenshots/` 必须包含步骤执行前后的截图证据。
- 报告必须可以脱离 API 单独查看。

## 6. 本地验证要求

在没有真实飞书窗口、没有真实模型 Key 的情况下，必须可以用 `mock + dry_run` 跑通。

推荐命令：

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
$env:CUA_LARK_MODEL_PROVIDER="mock"
$env:DRY_RUN="true"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="true"
python cli.py run-case cases\im_send_message.yaml
```

预期结果：

- 命令退出码为 `0`。
- 输出状态为 `pass`。
- IM 示例用例显示 `7/7 steps passed`。
- 运行目录中存在 `summary.json`、`summary.md`、`steps.jsonl` 和截图。

## 7. 多产品覆盖要求

至少需要能运行两个飞书子产品用例。当前提供三个示例：

- `cases\im_send_message.yaml`
- `cases\docs_create_doc.yaml`
- `cases\calendar_create_event.yaml`

推荐全部执行：

```powershell
python cli.py run-case cases\im_send_message.yaml
python cli.py run-case cases\docs_create_doc.yaml
python cli.py run-case cases\calendar_create_event.yaml
```

预期结果：

- IM 用例通过。
- Docs 用例通过。
- Calendar 用例通过。
- 每个用例都有独立报告目录和截图证据。

