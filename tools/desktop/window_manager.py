from __future__ import annotations


class WindowManager:
    def focus_lark(self) -> bool:
        # pywinauto/UIAutomation can be added here as a stronger Windows adapter.
        return True

    def get_active_window_title(self) -> str:
        return "Lark/Feishu"
