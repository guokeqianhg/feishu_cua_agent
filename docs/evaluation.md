# CUA-Lark 评估标准

## 单用例验收

一个 case 只有同时满足以下条件才算通过：

- `summary.md` 中 `Status=pass`。
- `Runtime Mode` 与预期一致，例如真实调试时 `Dry Run=False`、`Real Desktop Execution=True`。
- 每一步都有 before/after screenshot。
- `steps.jsonl` 能看到实际动作、坐标、输入、耗时和验证原因。
- mock/dry_run 报告明确提示“模拟验证不代表真实飞书操作成功”。
- 黑屏、纯色截图不能被当作正常 evidence。

## 安全 smoke 验收

`smoke_search_only.yaml` 和 `im_search_only.yaml` 通过时应满足：

- 飞书窗口可见。
- 搜索区域被点击或聚焦。
- 安全文本被输入。
- 没有进入发送动作。
- 没有使用 Enter 发送消息。

`docs_open_smoke.yaml` 通过时应满足：

- 截图健康。
- 尝试打开或切换到云文档入口。
- 不创建、不编辑、不保存任何文档。

## suite 验收

`safe_smoke_suite.yaml` 通过时应满足：

- IM 与 Docs 两个 product 都出现在 suite summary 中。
- 每个子 case 都有独立报告目录。
- suite 总报告显示全部 case pass。

## 完整 IM 发送验收

只有在以下条件全部满足后才允许测试 `im_send_message_guarded.yaml`：

- 当前使用测试群或测试联系人。
- `CUA_LARK_ALLOWED_IM_TARGET` 与 case 中 `metadata.target` 完全一致。
- `CUA_LARK_ALLOW_SEND_MESSAGE=true`。
- `smoke_search_only.yaml --auto-debug` 已稳定通过。
- `im_search_only.yaml --auto-debug` 已稳定通过。

如果安全开关未开启或目标不匹配，case 应该失败在发送保护阶段，而不是继续点击或发送。
