# Demo 脚本

## 1. 环境确认

```powershell
conda activate agent
cd D:\找工作\feishu_cua_agent\backend
python cli.py screenshot-diagnostics --configured-only
python cli.py inspect-screen
```

确认截图不是黑屏，网格图能看清飞书窗口。

## 2. IM 安全烟测

```powershell
$env:DRY_RUN="false"
$env:CUA_LARK_PLACEHOLDER_SCREENSHOT="false"
python cli.py run-case cases\smoke_search_only.yaml --auto-debug
```

预期：自动聚焦飞书、点击搜索、输入 `harmless-smoke-test`，不发送消息。

## 3. 双产品 suite

```powershell
python cli.py run-suite cases\safe_smoke_suite.yaml --auto-debug
```

预期：生成 suite 报告，覆盖 IM 和 Docs。

## 4. 受保护 IM 发送

只在测试群中执行：

```powershell
$env:CUA_LARK_ALLOW_SEND_MESSAGE="true"
$env:CUA_LARK_ALLOWED_IM_TARGET="测试群"
python cli.py run-case cases\im_send_message_guarded.yaml --auto-debug
```

如果没有设置安全开关，系统应阻止会话打开、草稿输入或发送动作。

