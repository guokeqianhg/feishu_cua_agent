# CUA-Lark 后端系统设计

## 目标

CUA-Lark 后端用于把自然语言或 YAML 测试用例转成可执行的飞书桌面 GUI 测试流程，并输出可回放、可审计的证据报告。

当前设计采用“通用 Agent 编排 + 产品工作流模板 + 本地快速验证 + VLM 兜底”的混合架构：

- 对稳定 demo 和安全 smoke，优先使用产品工作流模板和本地验证，减少 VLM 延迟与 JSON 解析风险。
- 对泛化自然语言任务，保留 OpenAI-compatible LLM/VLM 规划、观察、定位和验证能力。
- 对真实桌面执行，默认启用截图健康检查、mock 真实点击阻断、发送消息安全开关和 ABORT 中断机制。

## 核心模块

- `cli.py`：CLI 入口，支持 `run`、`run-case`、`run-suite`、`screenshot-diagnostics`、`inspect-screen`。
- `app/main.py`：FastAPI 入口，支持健康检查、运行任务、观察屏幕、截图诊断和报告查询。
- `agent/graph.py`：LangGraph 编排，串联截图、感知、规划、定位、执行、验证、恢复和报告。
- `products/workflows.py`：产品级确定性工作流模板，当前覆盖 IM 安全搜索、IM guarded 发送、Docs 安全入口烟测。
- `verification/registry.py`：本地验证注册表，先处理可快速验证的 case，再交给 VLM。
- `tools/capture/`：MSS 截图、黑屏/纯色检测、坐标网格诊断。
- `tools/desktop/`：PyAutoGUI/Pyperclip 执行鼠标、键盘、粘贴和窗口聚焦。
- `tools/vision/`：OCR、VLM client、解析和历史 smoke 视觉辅助。
- `storage/`：case 加载、运行日志、报告写入和 artifact 管理。

## 安全策略

- `DRY_RUN=false` 前会执行截图健康检查。
- 如果 `effective_model_provider=mock`，真实点击默认被阻止。
- `im_send_message_guarded.yaml` 的打开会话、草稿输入和发送动作受 `CUA_LARK_ALLOW_SEND_MESSAGE` 与 `CUA_LARK_ALLOWED_IM_TARGET` 保护。
- `runs/ABORT` 文件或 `Ctrl+C` 可以中断运行并生成 `aborted` 报告。
- 报告只记录运行模式、路径、坐标和验证结果，不记录 API Key 或 Authorization header。

## 运行证据

每次运行生成：

- `summary.json`
- `summary.md`
- `steps.jsonl`
- `screenshots/*_before_*.png`
- `screenshots/*_after_*.png`

suite 运行额外生成：

- `suite_summary.json`
- `suite_summary.md`
