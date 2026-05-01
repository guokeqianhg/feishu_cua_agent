from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import pyautogui


class WindowManager:
    KEYWORDS = ("飞书", "Feishu", "Lark")
    PROCESS_KEYWORDS = ("Feishu", "Lark")
    BROWSER_PROCESS_KEYWORDS = ("msedge", "chrome")

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32

    def focus_lark(self) -> bool:
        hwnd = self.find_lark_window()
        return self.focus_hwnd(hwnd)

    def minimize_lark(self) -> bool:
        hwnd = self.find_lark_window()
        if not hwnd:
            return False
        self.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        time.sleep(0.2)
        return True

    def minimize_active_window(self) -> bool:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return False
        self.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        time.sleep(0.2)
        return True

    def focus_window_by_keywords(self, keywords: list[str] | tuple[str, ...]) -> bool:
        hwnd = self.find_window_by_keywords(keywords)
        return self.focus_hwnd(hwnd)

    def focus_docs_editor(self) -> bool:
        hwnd = self.find_docs_editor_window()
        return self.focus_hwnd(hwnd)

    def focus_hwnd(self, hwnd: int | None) -> bool:
        if not hwnd:
            return False
        self.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        self.user32.BringWindowToTop(hwnd)
        self.user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        if self.user32.GetForegroundWindow() == hwnd:
            return True
        rect = self.window_rect(hwnd)
        if rect:
            left, top, right, bottom = rect
            x = max(left + min((right - left) // 2, 120), left + 20)
            y = max(top + min((bottom - top) // 2, 80), top + 20)
            pyautogui.click(x, y)
            time.sleep(0.2)
        return self.user32.GetForegroundWindow() == hwnd

    def get_active_window_title(self) -> str:
        hwnd = self.user32.GetForegroundWindow()
        return self._window_title(hwnd) if hwnd else ""

    def find_lark_window(self) -> int | None:
        process_matches: list[tuple[int, str]] = []
        title_matches: list[tuple[int, str]] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd: int, _lparam: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True
            title = self._window_title(hwnd)
            process_path = self._process_path(hwnd)
            process_haystack = process_path.lower()
            title_haystack = title.lower()
            if any(keyword.lower() in process_haystack for keyword in self.PROCESS_KEYWORDS):
                process_matches.append((hwnd, title))
            elif any(keyword.lower() in title_haystack for keyword in self.KEYWORDS):
                title_matches.append((hwnd, title))
            return True

        self.user32.EnumWindows(enum_proc, 0)
        matches = process_matches or title_matches
        if not matches:
            return None
        main_matches = [
            item
            for item in matches
            if not any(marker in item[1] for marker in ("会议", "Meeting", "meeting"))
        ]
        if main_matches:
            return main_matches[0][0]
        return matches[0][0]

    def find_lark_meeting_window(self) -> int | None:
        return self.find_window_by_keywords(("飞书会议", "椋炰功浼氳", "Feishu Meeting", "Lark Meeting"))

    def focus_lark_meeting(self) -> bool:
        hwnd = self.find_lark_meeting_window()
        return self.focus_hwnd(hwnd)

    def find_window_by_keywords(self, keywords: list[str] | tuple[str, ...]) -> int | None:
        normalized = [item.lower() for item in keywords if item]
        if not normalized:
            return None
        matches: list[tuple[int, str]] = []
        browser_matches: list[tuple[int, str]] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd: int, _lparam: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True
            title = self._window_title(hwnd)
            process_path = self._process_path(hwnd)
            if title and any(keyword in title.lower() for keyword in normalized):
                matches.append((hwnd, title))
            elif any(keyword in normalized for keyword in ("docs", "飞书云文档", "未命名文档")):
                if any(browser in process_path.lower() for browser in ("msedge", "chrome")):
                    browser_matches.append((hwnd, title))
            return True

        self.user32.EnumWindows(enum_proc, 0)
        matches = matches or browser_matches
        if not matches:
            return None
        # Prefer the most specific title match, which avoids grabbing a generic
        # Feishu desktop window when a browser tab title includes "飞书云文档".
        matches.sort(key=lambda item: len(item[1]), reverse=True)
        return matches[0][0]

    def find_docs_editor_window(self) -> int | None:
        matches: list[tuple[int, int, str]] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd: int, _lparam: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True
            title = self._window_title(hwnd)
            process_path = self._process_path(hwnd)
            process = process_path.lower()
            if not any(browser in process for browser in self.BROWSER_PROCESS_KEYWORDS):
                return True
            score = self._docs_editor_title_score(title)
            if score > 0:
                matches.append((hwnd, score, title))
            return True

        self.user32.EnumWindows(enum_proc, 0)
        if not matches:
            return None
        matches.sort(key=lambda item: (item[1], len(item[2])), reverse=True)
        return matches[0][0]

    @staticmethod
    def _docs_editor_title_score(title: str) -> int:
        raw = (title or "").lower()
        if not raw:
            return 0
        negative = ("chatgpt", "base app", "visual studio code", "powershell", "github")
        if any(item in raw for item in negative):
            return 0
        score = 0
        for keyword in ("未命名文档", "飞书云文档", "飞书文档", "docs", "wiki", "feishu"):
            if keyword.lower() in raw:
                score += 2
        if "edge" in raw or "chrome" in raw:
            score += 1
        return score

    def window_rect(self, hwnd: int | None = None) -> tuple[int, int, int, int] | None:
        target = hwnd or self.find_lark_window()
        if not target:
            return None
        rect = wintypes.RECT()
        if not self.user32.GetWindowRect(target, ctypes.byref(rect)):
            return None
        return rect.left, rect.top, rect.right, rect.bottom

    def _window_title(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        cleaned = (
            buffer.value.replace("\u200d", "")
            .replace("\u200c", "")
            .replace("\u2060", "")
            .replace("\ufeff", "")
        )
        return cleaned.encode("gbk", errors="replace").decode("gbk")

    def _process_path(self, hwnd: int) -> str:
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            query = kernel32.QueryFullProcessImageNameW
            query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            query.restype = wintypes.BOOL
            if query(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            return ""
        finally:
            kernel32.CloseHandle(handle)
