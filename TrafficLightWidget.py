"""Traffic Light Widget — a tiny floating Windows 11 desktop widget that shows
the current coding-activity status as a traffic light.

- Red:    actively coding (opencode / Copilot Chat is generating or using tools)
- Orange: asking the user (permission request or question pending)
- Green:  finished / idle

Supports two backends, switchable via right-click menu:
  1. opencode   — reads ~/.local/share/opencode/log/opencode.log
  2. Copilot    — reads ~/.copilot/session-state/<session>/events.jsonl

Dependency-free (Python stdlib + Tkinter + ctypes). No network, no credentials.

Run:    pythonw TrafficLightWidget.py
"""

import glob
import json
import math
import os
import random
import re
import sys
import threading
import time
import tkinter as tk
import winsound
from dataclasses import dataclass
from datetime import datetime, timezone
from tkinter import font as tkfont
from typing import List, Optional, Tuple

try:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
except Exception:
    pass


# --- palette -----------------------------------------------------------------

CARD_BG = "#1C1C1E"
CARD_BORDER = "#38383A"
RED = "#FF453A"
AMBER = "#FF9F0A"
GREEN = "#30D158"
INACTIVE = "#3A3A3C"
INACTIVE_BORDER = "#48484A"
TRANSPARENT = "#F0ABCD"

CARD_W, CARD_H = 72, 118
IDLE_GREEN = "#162D1E"
CIRCLE_R = 10
CIRCLE_GAP = 6
GLOW_STEPS = ((17, 0.12), (15, 0.25), (13, 0.45))


def _glow_blend(c, t):
    r1, g1, b1 = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    r2, g2, b2 = int(CARD_BG[1:3], 16), int(CARD_BG[3:5], 16), int(CARD_BG[5:7], 16)
    return f"#{int(r1*t+r2*(1-t)):02X}{int(g1*t+g2*(1-t)):02X}{int(b1*t+b2*(1-t)):02X}"

GLOW_RED = _glow_blend(RED, 0.4)
GLOW_AMBER = _glow_blend(AMBER, 0.4)
GLOW_GREEN = _glow_blend(GREEN, 0.4)

BACKENDS = ["opencode", "copilot", "codex", "auto"]

OPENCODE_LOG_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "opencode", "log")
COPILOT_SESSION_DIR = os.path.join(os.path.expanduser("~"), ".copilot", "session-state")
CODEX_SESSIONS_DIR = os.path.join(os.path.expanduser("~"), ".codex", "sessions")
STATE_DIR = os.path.join(os.path.expanduser("~"), ".config", "traffic-light-widget")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

ACTIVITY_TIMEOUT = 8.0
ASK_TIMEOUT = 30.0
POLL_INTERVAL = 2.0
TICK_INTERVAL = 1.0
TAIL_LINES = 256


# --- state types -------------------------------------------------------------

@dataclass
class LightState:
    color: str = "idle"
    label: str = "Idle"
    backend: str = "opencode"
    detail: str = ""


# --- helpers -----------------------------------------------------------------

def _parse_iso(ts: str) -> Optional[float]:
    try:
        s = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def _tail_file(path: str, n: int) -> List[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return []
            read_size = min(size, 8192 * n)
            f.seek(-read_size, 2)
            data = f.read(read_size)
            lines = data.decode("utf-8", errors="replace").splitlines()
            return lines[-n:]
    except Exception:
        return []


def _timestamp_from_log(line: str) -> Optional[float]:
    m = re.search(r'timestamp=([\dTZ.:+-]+)', line)
    if m:
        return _parse_iso(m.group(1))
    return None


def _load_json_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json_state(data: dict):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


# --- opencode backend --------------------------------------------------------

def compute_opencode(now: float) -> LightState:
    log_path = os.path.join(OPENCODE_LOG_DIR, "opencode.log")
    if not os.path.isfile(log_path):
        return LightState(color="idle", label="Idle", backend="opencode", detail="no log")

    lines = _tail_file(log_path, TAIL_LINES)

    last_work = 0.0
    last_ask = 0.0
    last_work_note = ""
    last_ask_note = ""

    for line in lines:
        ts = _timestamp_from_log(line)
        if ts is None:
            continue

        if "message=stream" in line:
            if ts > last_work:
                last_work = ts
                last_work_note = "stream"

        if "message=loop" in line or "message=process" in line:
            if ts > last_work:
                last_work = ts
                last_work_note = "loop/process"

        if "message=tracking" in line:
            if ts > last_work:
                last_work = ts
                last_work_note = "tracking"

        if '"touching file"' in line or '"resolved path"' in line:
            if ts > last_work:
                last_work = ts
                last_work_note = "file"

        if "action.action=allow" in line:
            if ts > last_work:
                last_work = ts
                last_work_note = "tool"

        if "message=asking id=que_" in line:
            if ts > last_ask:
                last_ask = ts
                last_ask_note = "question"

        if "action.action=ask" in line:
            if ts > last_ask:
                last_ask = ts
                last_ask_note = "permission"

    if last_work > 0 and (now - last_work) < ACTIVITY_TIMEOUT:
        st = LightState(color="red", label="Coding", backend="opencode")
        if "tool" in last_work_note:
            st.detail = "tool"
        else:
            st.detail = "generating"
        return st

    if last_ask > 0 and last_ask > last_work and (now - last_ask) < ASK_TIMEOUT:
        return LightState(
            color="orange", label="Asking", backend="opencode",
            detail=last_ask_note or "permission"
        )

    if last_work > 0 and (now - last_work) < ASK_TIMEOUT:
        return LightState(color="green", label="Done", backend="opencode", detail="recent")

    return LightState(color="idle", label="Idle", backend="opencode")


# --- Copilot backend ---------------------------------------------------------

def _find_copilot_events() -> Optional[str]:
    if not os.path.isdir(COPILOT_SESSION_DIR):
        return None
    best = None
    best_mtime = 0
    for root, dirs, files in os.walk(COPILOT_SESSION_DIR):
        for f in files:
            if f == "events.jsonl":
                fp = os.path.join(root, f)
                try:
                    mt = os.path.getmtime(fp)
                    if mt > best_mtime:
                        best_mtime = mt
                        best = fp
                except OSError:
                    continue
    return best


def compute_copilot(now: float) -> LightState:
    source = _find_copilot_events()
    if not source:
        return LightState(color="idle", label="Idle", backend="copilot", detail="no session")

    lines = _tail_file(source, TAIL_LINES)

    turn_active = False
    tool_active = False
    tool_start_time = 0.0
    last_user_msg = 0.0
    last_assistant_msg = 0.0
    assistant_msg_content = ""
    session_active = False

    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue

        ev = obj.get("type", "")
        ts_str = obj.get("timestamp")
        ts = _parse_iso(ts_str) if isinstance(ts_str, str) else None
        if ts is None:
            continue

        if ev == "assistant.turn_start":
            turn_active = True
            session_active = True
        elif ev == "assistant.turn_end":
            turn_active = False
            tool_active = False
        elif ev == "tool.execution_start":
            tool_active = True
            tool_start_time = ts
        elif ev == "tool.execution_complete":
            tool_active = False
        elif ev == "user.message":
            last_user_msg = ts
            session_active = True
        elif ev == "assistant.message":
            last_assistant_msg = ts
            content = obj.get("data", {}).get("content", "")
            if content:
                assistant_msg_content = content
        elif ev == "session.shutdown":
            turn_active = False
            tool_active = False
            session_active = False

    if turn_active:
        if tool_active and tool_start_time > 0 and (now - tool_start_time) > 2.0:
            return LightState(
                color="orange", label="Asking", backend="copilot",
                detail="tool approval"
            )

        if assistant_msg_content and assistant_msg_content.rstrip().endswith(("?", "\u00BF")):
            if last_assistant_msg > tool_start_time:
                return LightState(
                    color="orange", label="Asking", backend="copilot",
                    detail="question"
                )

        return LightState(color="red", label="Coding", backend="copilot",
                          detail="turn active")

    if last_user_msg > 0 and (now - last_user_msg) < ACTIVITY_TIMEOUT:
        return LightState(
            color="red", label="Coding", backend="copilot",
            detail="user sent msg"
        )

    if session_active and turn_active is False:
        last_any = max(t for t in [last_assistant_msg, last_user_msg,
                                    tool_start_time] if t > 0)
        if last_any > 0 and (now - last_any) < ASK_TIMEOUT:
            return LightState(
                color="green", label="Done", backend="copilot",
                detail="recent"
            )

    return LightState(color="idle", label="Idle", backend="copilot")


# --- Codex backend -----------------------------------------------------------

def _find_codex_session() -> Optional[str]:
    if not os.path.isdir(CODEX_SESSIONS_DIR):
        return None
    best = None
    best_mtime = 0
    for root, dirs, files in os.walk(CODEX_SESSIONS_DIR):
        for f in files:
            if f.startswith("rollout-") and f.endswith(".jsonl"):
                fp = os.path.join(root, f)
                try:
                    mt = os.path.getmtime(fp)
                    if mt > best_mtime:
                        best_mtime = mt
                        best = fp
                except OSError:
                    continue
    return best


def compute_codex(now: float) -> LightState:
    source = _find_codex_session()
    if not source:
        return LightState(color="idle", label="Idle", backend="codex", detail="no session")

    lines = _tail_file(source, TAIL_LINES)

    last_activity = 0.0
    last_func_call = 0.0
    last_ask = 0.0
    assistant_msg_content = ""

    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue

        ts_str = obj.get("timestamp")
        ts = _parse_iso(ts_str) if isinstance(ts_str, str) else None
        if ts is None:
            continue

        ev = obj.get("type", "")

        if ev == "response_item":
            pl = obj.get("payload", {})
            pt = pl.get("type", "")
            if pt == "function_call":
                if ts > last_func_call:
                    last_func_call = ts
                last_activity = max(last_activity, ts)
            elif pt in ("function_call_output", "tool_use"):
                last_activity = max(last_activity, ts)
            elif pt == "message":
                last_activity = max(last_activity, ts)
                for c in pl.get("content", []):
                    if c.get("type") == "output_text":
                        content = c.get("text", "")
                        if content:
                            assistant_msg_content = content

        elif ev == "event_msg":
            pl = obj.get("payload", {})
            pt = pl.get("type", "")
            if pt == "token_count":
                last_activity = max(last_activity, ts)
            elif pt == "agent_message":
                msg = pl.get("message", "")
                last_activity = max(last_activity, ts)
                if msg:
                    assistant_msg_content = msg
            elif pt == "ask_user":
                if ts > last_ask:
                    last_ask = ts

    if last_func_call > 0 and (now - last_func_call) < ACTIVITY_TIMEOUT:
        return LightState(
            color="red", label="Coding", backend="codex", detail="tool execution"
        )

    if last_activity > 0 and (now - last_activity) < ACTIVITY_TIMEOUT:
        if assistant_msg_content and assistant_msg_content.rstrip().endswith(("?", "\u00BF")):
            if last_ask == 0 or last_activity > last_ask:
                return LightState(color="orange", label="Asking", backend="codex", detail="question")
        return LightState(color="red", label="Coding", backend="codex", detail="active")

    if last_ask > 0 and last_ask > last_activity and (now - last_ask) < ASK_TIMEOUT:
        return LightState(color="orange", label="Asking", backend="codex", detail="pending")

    if last_activity > 0 and (now - last_activity) < ASK_TIMEOUT:
        return LightState(color="green", label="Done", backend="codex", detail="recent")

    return LightState(color="idle", label="Idle", backend="codex")


# --- auto backend selector ---------------------------------------------------

def compute_auto(now: float) -> LightState:
    states = [compute_opencode(now), compute_copilot(now), compute_codex(now)]
    active = [s for s in states if s.color != "idle"]
    if active:
        active[0].backend = "auto"
        return active[0]
    return LightState(color="idle", label="Idle", backend="auto")


# --- drawing helpers ---------------------------------------------------------

def round_rect_pts(x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    n = 10
    pts = []
    cx = [x + w - r, x + w - r, x + r, x + r]
    cy = [y + r, y + h - r, y + h - r, y + r]
    start = [270, 0, 90, 180]
    for i in range(4):
        for j in range(n + 1):
            a = math.radians(start[i] + j * 90 / n)
            pts.append(cx[i] + r * math.cos(a))
            pts.append(cy[i] + r * math.sin(a))
    return pts


class Canvas:
    def __init__(self, tk_canvas, scale):
        self.c = tk_canvas
        self.S = scale

    def rrect(self, x, y, w, h, r, **kw):
        pts = round_rect_pts(x * self.S, y * self.S, w * self.S, h * self.S, r * self.S)
        return self.c.create_polygon(pts, smooth=False, **kw)

    def rect(self, x, y, w, h, **kw):
        return self.c.create_rectangle(x * self.S, y * self.S,
                                       (x + w) * self.S, (y + h) * self.S, **kw)

    def oval(self, cx, cy, rx, ry, **kw):
        return self.c.create_oval((cx - rx) * self.S, (cy - ry) * self.S,
                                  (cx + rx) * self.S, (cy + ry) * self.S, **kw)

    def text(self, x, y, s, **kw):
        return self.c.create_text(x * self.S, y * self.S, text=s, **kw)


# --- system tray (Windows, stdlib ctypes) ------------------------------------

HAS_TRAY = False
try:
    import ctypes
    from ctypes import wintypes
    HAS_TRAY = True
except Exception:
    pass

if HAS_TRAY:
    _U32 = ctypes.windll.user32
    _S32 = ctypes.windll.shell32
    _K32 = ctypes.windll.kernel32
    _G32 = ctypes.windll.gdi32

    _WM_APP = 0x8000
    _WM_TRAY = _WM_APP + 1
    _WM_CLOSE_TRAY = _WM_APP + 2
    _WM_LBUTTONUP = 0x0202
    _WM_RBUTTONUP = 0x0205

    _NIM_ADD = 0
    _NIM_MODIFY = 1
    _NIM_DELETE = 2
    _NIF_MESSAGE = 0x01
    _NIF_ICON = 0x02
    _NIF_TIP = 0x04
    _TPM_RETURNCMD = 0x0100
    _MF_SEPARATOR = 0x0800

    _WNDPROC = ctypes.WINFUNCTYPE(
        wintypes.LPARAM, wintypes.HWND, wintypes.UINT,
        wintypes.WPARAM, wintypes.LPARAM)

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

    class _NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD), ("guidItem", _GUID),
            ("hBalloonIcon", wintypes.HICON),
        ]

    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
            ("lpfnWndProc", _WNDPROC), ("cbClsExtra", wintypes.INT),
            ("cbWndExtra", wintypes.INT), ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    _U32.CreateWindowExW.restype = wintypes.HWND
    _U32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        wintypes.INT, wintypes.INT, wintypes.INT, wintypes.INT,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    _U32.CreatePopupMenu.restype = wintypes.HMENU
    _U32.DefWindowProcW.restype = wintypes.LPARAM
    _U32.DefWindowProcW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _U32.GetMessageW.restype = wintypes.BOOL
    _U32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _U32.PostMessageW.restype = wintypes.BOOL
    _U32.PostMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _U32.DestroyWindow.restype = wintypes.BOOL
    _U32.DestroyWindow.argtypes = [wintypes.HWND]
    _U32.AppendMenuW.restype = wintypes.BOOL
    _U32.AppendMenuW.argtypes = [
        wintypes.HMENU, wintypes.UINT, wintypes.UINT, wintypes.LPCWSTR]
    _U32.DestroyMenu.restype = wintypes.BOOL
    _U32.DestroyMenu.argtypes = [wintypes.HMENU]
    _U32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _U32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _U32.TrackPopupMenuEx.restype = wintypes.UINT
    _U32.TrackPopupMenuEx.argtypes = [
        wintypes.HMENU, wintypes.UINT, wintypes.INT, wintypes.INT,
        wintypes.HWND, ctypes.c_void_p]
    _S32.Shell_NotifyIconW.restype = wintypes.BOOL
    _S32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]

    _U32.CreateIconIndirect.restype = wintypes.HICON
    _U32.CreateIconIndirect.argtypes = [ctypes.c_void_p]
    _U32.DestroyIcon.argtypes = [wintypes.HICON]
    _G32.CreateCompatibleDC.restype = wintypes.HDC
    _G32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _G32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _G32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, wintypes.INT, wintypes.INT]
    _G32.CreateBitmap.restype = wintypes.HBITMAP
    _G32.CreateBitmap.argtypes = [
        wintypes.INT, wintypes.INT, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
    _G32.SelectObject.restype = wintypes.HGDIOBJ
    _G32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _G32.DeleteDC.argtypes = [wintypes.HDC]
    _G32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _G32.CreateSolidBrush.restype = wintypes.HBRUSH
    _G32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    _G32.Ellipse.argtypes = [
        wintypes.HDC, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.INT]
    _G32.Polygon.restype = wintypes.BOOL
    _G32.Polygon.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.INT]
    _G32.PatBlt.restype = wintypes.BOOL
    _G32.PatBlt.argtypes = [
        wintypes.HDC, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.DWORD]
    _G32.SetPixelV.argtypes = [
        wintypes.HDC, wintypes.INT, wintypes.INT, wintypes.COLORREF]
    _G32.GetDeviceCaps.argtypes = [wintypes.HDC, wintypes.INT]
    _U32.GetDC.restype = wintypes.HDC
    _U32.GetDC.argtypes = [wintypes.HWND]
    _U32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

    _PS_SOLID = 0

    class _ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP),
        ]

    def _hex_to_bgr(h: str) -> int:
        r = int(h[1:3], 16)
        g = int(h[3:5], 16)
        b = int(h[5:7], 16)
        return (b << 16) | (g << 8) | r

    _TRAY_ACTIVE = {"red": 0, "orange": 1, "green": 2, "idle": -1}

    def _create_tray_icon(size=64, active="idle"):
        cx = cy = size // 2
        outer_r = size // 2 - 1
        inner_r = max(4, outer_r - 4)
        active_idx = _TRAY_ACTIVE.get(active, -1)

        colors = [_hex_to_bgr(RED), _hex_to_bgr(AMBER), _hex_to_bgr(GREEN)]
        fill = colors[active_idx] if active_idx >= 0 else _hex_to_bgr(IDLE_GREEN)
        ring = _hex_to_bgr(INACTIVE)

        hdc_screen = _U32.GetDC(None)
        hdc = _G32.CreateCompatibleDC(hdc_screen)
        hbm_color = _G32.CreateCompatibleBitmap(hdc_screen, size, size)
        hbm_mask = _G32.CreateBitmap(size, size, 1, 1, None)
        _U32.ReleaseDC(None, hdc_screen)

        old_bm = _G32.SelectObject(hdc, hbm_color)
        bg = _G32.CreateSolidBrush(0xFF00FF)
        _G32.SelectObject(hdc, bg)
        _G32.PatBlt(hdc, 0, 0, size, size, 0x0042)
        _G32.DeleteObject(bg)

        brush = _G32.CreateSolidBrush(ring)
        _G32.SelectObject(hdc, brush)
        _G32.Ellipse(hdc, cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r)
        _G32.DeleteObject(brush)

        brush = _G32.CreateSolidBrush(fill)
        _G32.SelectObject(hdc, brush)
        _G32.Ellipse(hdc, cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r)
        _G32.DeleteObject(brush)

        _G32.SelectObject(hdc, old_bm)
        _G32.DeleteDC(hdc)

        hdc_mask = _G32.CreateCompatibleDC(None)
        old_mask = _G32.SelectObject(hdc_mask, hbm_mask)
        _G32.PatBlt(hdc_mask, 0, 0, size, size, 0x0042)
        mask_brush = _G32.CreateSolidBrush(0x000000)
        _G32.SelectObject(hdc_mask, mask_brush)
        _G32.Ellipse(hdc_mask, cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r)
        _G32.DeleteObject(mask_brush)
        _G32.SelectObject(hdc_mask, old_mask)
        _G32.DeleteDC(hdc_mask)

        ii = _ICONINFO()
        ii.fIcon = True
        ii.xHotspot = cx
        ii.yHotspot = cy
        ii.hbmMask = hbm_mask
        ii.hbmColor = hbm_color
        hicon = _U32.CreateIconIndirect(ctypes.byref(ii))
        _G32.SelectObject(hdc, old_bm)
        _G32.DeleteObject(hbm_color)
        _G32.DeleteObject(hbm_mask)
        return hicon

    class TrayIcon:
        def __init__(self, tooltip, on_show, on_quit):
            self._tooltip = tooltip[:127]
            self._on_show = on_show
            self._on_quit = on_quit
            self._hwnd = None
            self._hicon = None
            self._nid = None
            self._thread = None
            self._wndproc_ref = None
            self._cls_name = "TrafficLightTray"
            self._hinst = _K32.GetModuleHandleW(None)
            self._current_state = "idle"

        def start(self):
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

        def _run(self):
            try:
                self._run_inner()
            except Exception as e:
                print(f"TrayIcon error: {e}", file=sys.stderr)

        def _run_inner(self):
            def proc(hwnd, msg, wparam, lparam):
                if msg == _WM_TRAY:
                    mouse = lparam & 0xFFFF
                    if mouse == _WM_LBUTTONUP:
                        self._on_show()
                    elif mouse == _WM_RBUTTONUP:
                        self._show_menu(hwnd)
                    return 0
                if msg == _WM_CLOSE_TRAY:
                    _U32.DestroyWindow(hwnd)
                    return 0
                if msg == 0x0002:
                    _U32.PostQuitMessage(0)
                    return 0
                return _U32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc_ref = _WNDPROC(proc)

            wc = _WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(wc)
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = self._hinst
            wc.lpszClassName = self._cls_name
            _U32.RegisterClassExW(ctypes.byref(wc))

            self._hwnd = _U32.CreateWindowExW(
                0, self._cls_name, "Traffic Light", 0, 0, 0, 0, 0,
                ctypes.c_void_p(-3), None, self._hinst, None)

            self._hicon = _create_tray_icon(64, "idle")
            self._current_state = "idle"

            nid = _NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = self._hwnd
            nid.uID = 1
            nid.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
            nid.uCallbackMessage = _WM_TRAY
            nid.hIcon = self._hicon
            nid.szTip = self._tooltip
            _S32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid))
            self._nid = nid

            msg = wintypes.MSG()
            while _U32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _U32.TranslateMessage(ctypes.byref(msg))
                _U32.DispatchMessageW(ctypes.byref(msg))

            if self._nid:
                _S32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._nid))
            if self._hwnd:
                _U32.DestroyWindow(self._hwnd)
            if self._hicon:
                _U32.DestroyIcon(self._hicon)
            _U32.UnregisterClassW(self._cls_name, self._hinst)

        def _show_menu(self, hwnd):
            menu = _U32.CreatePopupMenu()
            _U32.AppendMenuW(menu, 0, 1, "Show widget")
            _U32.AppendMenuW(menu, _MF_SEPARATOR, 0, "")
            _U32.AppendMenuW(menu, 0, 2, "Quit")
            pt = wintypes.POINT()
            _U32.GetCursorPos(ctypes.byref(pt))
            _U32.SetForegroundWindow(hwnd)
            cmd = _U32.TrackPopupMenuEx(
                menu, _TPM_RETURNCMD, pt.x, pt.y, hwnd, None)
            _U32.DestroyMenu(menu)
            if cmd == 1:
                self._on_show()
            elif cmd == 2:
                self._on_quit()

        def update_tooltip(self, text):
            if not self._nid or not self._hwnd:
                return
            self._nid.szTip = text[:127]
            _S32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(self._nid))

        def update_icon(self, state: str):
            if not self._nid or not self._hwnd:
                return
            if state == self._current_state:
                return
            self._current_state = state
            new_icon = _create_tray_icon(64, state)
            if new_icon:
                self._nid.hIcon = new_icon
                _S32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(self._nid))
                if self._hicon:
                    _U32.DestroyIcon(self._hicon)
                self._hicon = new_icon

        def stop(self):
            if self._hwnd:
                _U32.PostMessageW(self._hwnd, _WM_CLOSE_TRAY, 0, 0)
else:
    class TrayIcon:
        def __init__(self, *a, **kw):
            pass
        def start(self):
            pass
        def stop(self):
            pass
        def update_tooltip(self, text):
            pass
        def update_icon(self, state):
            pass


# --- widget app --------------------------------------------------------------


class WidgetApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.config(bg=TRANSPARENT)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except Exception:
            pass

        dpi = self.root.winfo_fpixels("1i")
        self.S = max(1.0, dpi / 96.0)

        self.state = LightState(color="idle", label="Idle", backend="opencode")
        self.on_top = True
        self._idle_since = None
        self._hidden_by_auto = False
        self._manually_hidden = False
        self._prev_color = None
        self._gradient_mode = False
        self._gradient_top = "#1C1C1E"
        self._gradient_bottom = "#2A2A2E"

        saved = _load_json_state()
        self.backend = saved.get("backend", "opencode")

        w, h = CARD_W, CARD_H
        self.canvas = tk.Canvas(root, bg=TRANSPARENT, highlightthickness=0,
                                width=int(w * self.S), height=int(h * self.S))
        self.canvas.pack()

        self.cv = Canvas(self.canvas, self.S)

        self._fonts = {
            "title": tkfont.Font(size=int(11 * self.S), weight="bold",
                                 family="Segoe UI"),
            "sub": tkfont.Font(size=int(9 * self.S), weight="normal",
                               family="Segoe UI"),
        }

        self._drag = None
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_right)
        self.canvas.bind("<Button-2>", self._on_right)

        self._place(saved)
        self._menu = self._build_menu()
        self.refresh_data()
        self.render()

        self._tray = TrayIcon(
            "Traffic Light Widget",
            on_show=lambda: self.root.after(0, self._show_from_tray),
            on_quit=lambda: self.root.after(0, self.quit),
        )
        self._tray.start()

        self.root.after(int(TICK_INTERVAL * 1000), self._tick)
        self.root.after(int(POLL_INTERVAL * 1000), self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

    def _place(self, saved: dict):
        w, h = CARD_W, CARD_H
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        frame = saved.get("frame")
        if frame and isinstance(frame, str) and "+" in frame:
            try:
                xs = frame.split("+")
                x, y = int(xs[-2]), int(xs[-1])
                if 0 <= x <= sw - 40 and 0 <= y <= sh - 40:
                    self.root.geometry(f"+{x}+{y}")
                    return
            except Exception:
                pass
        x = sw - int(w * self.S) - int(24 * self.S)
        y = int(96 * self.S)
        self.root.geometry(f"+{x}+{y}")

    def _save_state(self):
        data = _load_json_state()
        data["backend"] = self.backend
        data["frame"] = f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
        _save_json_state(data)

    def _build_menu(self) -> tk.Menu:
        m = tk.Menu(self.root, tearoff=0)
        backend_menu = tk.Menu(m, tearoff=0)
        for b in BACKENDS:
            label = b.capitalize()
            check = "\u2713 " if self.backend == b else "   "
            backend_menu.add_command(
                label=f"{check}{label}",
                command=lambda bk=b: self._switch_backend(bk))
        m.add_cascade(label="Backend", menu=backend_menu)
        m.add_command(label="Always on top", command=self.toggle_top)
        m.add_command(label="Refresh now", command=self.refresh_now)
        m.add_command(label="\uD83C\uDFA8 Mood light", command=self._toggle_gradient)
        m.add_separator()
        m.add_command(label="Hide to tray", command=self._hide_to_tray)
        m.add_command(label="Quit", command=self.quit)
        return m

    def _rebuild_menu(self):
        self._menu = self._build_menu()

    def _switch_backend(self, bk: str):
        self.backend = bk
        self._rebuild_menu()
        self.refresh_data()
        self.render()
        self._save_state()

    def _on_press(self, e):
        self._drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _on_drag(self, e):
        if not self._drag:
            return
        dx = e.x_root - self._drag[0]
        dy = e.y_root - self._drag[1]
        self.root.geometry(f"+{self._drag[2] + dx}+{self._drag[3] + dy}")

    def _on_release(self, e):
        self._save_state()
        self._drag = None

    def _on_right(self, e):
        self._menu.tk_popup(e.x_root, e.y_root)

    def toggle_top(self):
        self.on_top = not self.on_top
        self.root.attributes("-topmost", self.on_top)

    def _random_hex(self):
        return f"#{random.randint(0,255):02X}{random.randint(0,255):02X}{random.randint(0,255):02X}"

    def _toggle_gradient(self):
        self._gradient_mode = not self._gradient_mode
        if self._gradient_mode:
            self._gradient_top = self._random_hex()
            self._gradient_bottom = self._random_hex()
        self.render()

    def refresh_now(self):
        self.refresh_data()
        self.render()

    def refresh_data(self):
        now = time.time()
        if self.backend == "auto":
            self.state = compute_auto(now)
        elif self.backend == "copilot":
            self.state = compute_copilot(now)
        elif self.backend == "codex":
            self.state = compute_codex(now)
        else:
            self.state = compute_opencode(now)

    def _hide_to_tray(self):
        self._save_state()
        self._manually_hidden = True
        self._hidden_by_auto = False
        self.root.withdraw()

    def _auto_hide(self):
        if self.root.state() != "withdrawn":
            self._save_state()
            self._hidden_by_auto = True
            self.root.withdraw()

    def _auto_show(self):
        if self.root.state() == "withdrawn" and self._hidden_by_auto:
            self._hidden_by_auto = False
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(100, lambda: self.root.attributes("-topmost", self.on_top))

    def _show_from_tray(self):
        self._manually_hidden = False
        self._hidden_by_auto = False
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(100, lambda: self.root.attributes("-topmost", self.on_top))

    def quit(self):
        self._save_state()
        if hasattr(self, "_tray"):
            self._tray.stop()
        self.root.destroy()

    def _tick(self):
        self.render()
        self.root.after(int(TICK_INTERVAL * 1000), self._tick)

    def _poll(self):
        now = time.time()

        oc_state = compute_opencode(now)
        cp_state = compute_copilot(now)
        cx_state = compute_codex(now)
        either_active = oc_state.color != "idle" or cp_state.color != "idle" or cx_state.color != "idle"

        self.refresh_data()

        cur = self.state.color
        if self._prev_color in ("red", "orange") and cur in ("green", "idle"):
            try:
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass
        self._prev_color = cur

        if not either_active:
            if self._idle_since is None:
                self._idle_since = now
            elif now - self._idle_since > 60:
                if not self._manually_hidden:
                    self._auto_hide()
        else:
            self._idle_since = None
            self._auto_show()

        self.root.after(int(POLL_INTERVAL * 1000), self._poll)

    def _circle_center(self, i):
        cx = CARD_W // 2
        total_circles = 3
        total_height = total_circles * CIRCLE_R * 2 + (total_circles - 1) * CIRCLE_GAP
        start_y = (CARD_H - total_height) // 2 + CIRCLE_R
        cy = start_y + i * (CIRCLE_R * 2 + CIRCLE_GAP)
        return cx, cy

    def render(self):
        c = self.canvas
        c.delete("all")
        w, h = CARD_W, CARD_H
        CR = 14

        if self._gradient_mode:
            tcol = self._gradient_top
            bcol = self._gradient_bottom
            r1 = int(tcol[1:3],16); g1 = int(tcol[3:5],16); b1 = int(tcol[5:7],16)
            r2 = int(bcol[1:3],16); g2 = int(bcol[3:5],16); b2 = int(bcol[5:7],16)

            self.cv.rrect(0, 0, w, h, CR, fill=tcol, outline="")

            body_top = CR
            body_bot = h - CR
            bands = 16
            bh = (body_bot - body_top) / bands
            for i in range(bands):
                t = i / (bands - 1)
                col = f"#{int(r1+(r2-r1)*t):02X}{int(g1+(g2-g1)*t):02X}{int(b1+(b2-b1)*t):02X}"
                self.cv.rect(0, body_top + i * bh, w, bh + 1, fill=col, outline="")

            self.cv.rrect(0, 0, w, h, CR, fill="", outline=CARD_BORDER)
        else:
            self.cv.rrect(0, 0, w, h, CR, fill=CARD_BG, outline="")
            self.cv.rrect(0, 0, w, h, CR, fill="", outline=CARD_BORDER)

        st = self.state
        names = ["red", "orange", "green"]
        fills = [RED, AMBER, GREEN]
        glows = [GLOW_RED, GLOW_AMBER, GLOW_GREEN]

        is_idle = st.color == "idle"

        for i, (an, col, glow) in enumerate(zip(names, fills, glows)):
            cx, cy = self._circle_center(i)
            is_active = st.color == an

            if is_active:
                for glow_r, intensity in GLOW_STEPS:
                    blend = _glow_blend(col, intensity)
                    self.cv.oval(cx, cy, glow_r, glow_r, fill=blend, outline="")
                self.cv.oval(cx, cy, CIRCLE_R, CIRCLE_R, fill=col, outline="")
            elif is_idle and an == "green":
                luma = _glow_blend(GREEN, 0.12)
                self.cv.oval(cx, cy, CIRCLE_R, CIRCLE_R,
                             fill=IDLE_GREEN, outline="#2A4A35")
            else:
                self.cv.oval(cx, cy, CIRCLE_R, CIRCLE_R,
                             fill=INACTIVE, outline=INACTIVE_BORDER)

        if hasattr(self, "_tray"):
            backend_label = {"opencode": "OC", "copilot": "CP", "codex": "CX", "auto": "AU"}.get(st.backend, st.backend)
            tip = f"{st.color} · {backend_label}"
            self._tray.update_tooltip(tip)
            self._tray.update_icon(st.color)

    def run(self):
        self.root.mainloop()


# --- snapshot rendering (Pillow, optional) -----------------------------------

def write_snapshot(path: str, active_index: int = 0):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow not installed — skipping snapshot", file=sys.stderr)
        return

    scale = 3
    w, h = CARD_W * scale, CARD_H * scale
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def rrect(x, y, ww, hh, r, **kw):
        d.rounded_rectangle([x, y, x + ww, y + hh], radius=r, **kw)

    rrect(0, 0, w, h, 14 * scale, fill=CARD_BG)
    rrect(0, 0, w, h, 14 * scale, fill=None, outline=CARD_BORDER)

    cx = CARD_W * scale // 2
    total = 3 * CIRCLE_R * 2 * scale + 2 * CIRCLE_GAP * scale
    start_y = (CARD_H * scale - total) // 2 + CIRCLE_R * scale
    cr = CIRCLE_R * scale
    cgap = CIRCLE_GAP * scale

    fills = [RED, AMBER, GREEN]

    for i in range(3):
        y_pos = start_y + i * (cr * 2 + cgap)
        col = fills[i]
        is_active = i == active_index

        if is_active:
            for glow_r, intensity in GLOW_STEPS:
                gr = glow_r * scale
                blend = _glow_blend(col, intensity)
                rrect(cx - gr, y_pos - gr, gr * 2, gr * 2, gr, fill=blend)
            rrect(cx - cr, y_pos - cr, cr * 2, cr * 2, cr, fill=col)
        else:
            rrect(cx - cr, y_pos - cr, cr * 2, cr * 2, cr, fill=INACTIVE, outline=INACTIVE_BORDER)

    img.save(path)
    print(f"snapshot: {path}")


# --- icon rendering (Pillow, optional) ---------------------------------------

def write_icon(path: str, png_path: Optional[str] = None):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow not installed — skipping icon", file=sys.stderr)
        return
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    outer = size // 2 - 6
    inner = outer - 18
    d.ellipse([cx - outer, cy - outer, cx + outer, cy + outer], fill=INACTIVE)
    d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=GREEN)
    img.save(path, format="ICO",
             sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"icon: {path}")
    if png_path:
        img.save(png_path, format="PNG")
        print(f"icon png: {png_path}")


# --- main --------------------------------------------------------------------

def main():
    if "--snapshot" in sys.argv:
        path = sys.argv[-1] if sys.argv[-1].endswith(".png") else "traffic-light-widget.png"
        write_snapshot(path)
        return
    if "--icon" in sys.argv:
        ico_path = sys.argv[-1] if sys.argv[-1].endswith(".ico") else "traffic-light-icon.ico"
        png_path = ico_path[:-4] + ".png" if ico_path.endswith(".ico") else "traffic-light-icon.png"
        write_icon(ico_path, png_path)
        return
    root = tk.Tk()
    WidgetApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
