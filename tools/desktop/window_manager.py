from __future__ import annotations

import ctypes
import time
from ctypes import wintypes


class WindowManager:
    KEYWORDS = ("飞书", "Feishu", "Lark")
    PROCESS_KEYWORDS = ("Feishu", "Lark")

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32

    def focus_lark(self) -> bool:
        hwnd = self.find_lark_window()
        if not hwnd:
            return False
        self.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        self.user32.BringWindowToTop(hwnd)
        self.user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        return self.user32.GetForegroundWindow() == hwnd

    def get_active_window_title(self) -> str:
        hwnd = self.user32.GetForegroundWindow()
        return self._window_title(hwnd) if hwnd else ""

    def find_lark_window(self) -> int | None:
        matches: list[tuple[int, str]] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd: int, _lparam: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True
            title = self._window_title(hwnd)
            process_path = self._process_path(hwnd)
            haystack = f"{title} {process_path}".lower()
            if any(keyword.lower() in haystack for keyword in (*self.KEYWORDS, *self.PROCESS_KEYWORDS)):
                matches.append((hwnd, title))
            return True

        self.user32.EnumWindows(enum_proc, 0)
        if not matches:
            return None
        return matches[0][0]

    def _window_title(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

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
