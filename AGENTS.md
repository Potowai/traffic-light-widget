# Traffic Light Widget — agent context

## What this is
A tiny floating **Windows 11** desktop widget that shows your AI coding
agent's activity as a traffic light: **Red** (coding), **Orange** (asking),
**Green** (finished). Supports two backends — **opencode** and **Copilot Chat**
— switchable via right-click menu.

No network, no credentials — reads local log files only.

## Environment
- OS: Windows 11
- Python 3.14 at `C:\Python314\python.exe` (and `pythonw.exe` for no-console launch)
- Tkinter 8.6 is in the stdlib (no pip needed to run the widget)

## Commands
- Run widget (no install): `pythonw TrafficLightWidget.py`
- Run with console (debug): `python TrafficLightWidget.py`  (blocks on mainloop)
- Render README snapshot + icon: `powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1`
- Install: `powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1`
- Uninstall: `powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1`
- Compute test: `python -c "import TrafficLightWidget as T; print(T.compute_opencode())"`
- Render check: `python -c "import importlib.util, tkinter as tk; spec=importlib.util.spec_from_file_location('tw', r'TrafficLightWidget.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); root=tk.Tk(); a=m.WidgetApp(root); root.update(); print('RENDER OK', a.canvas.winfo_reqwidth(), a.canvas.winfo_reqheight()); root.destroy()"`
- Compute test: `python -c "import TrafficLightWidget as T, time; s=T.compute_opencode(time.time()); print(str(s.color), str(s.label))"`
- Compute test (copilot): `python -c "import TrafficLightWidget as T, time; s=T.compute_copilot(time.time()); print(str(s.color), str(s.label))"`
- No tests / lint configured yet.

## File layout
| file | role |
|---|---|
| `TrafficLightWidget.py` | the widget (stdlib + Tkinter + ctypes, ~780 lines) |
| `install.ps1` / `uninstall.ps1` | per-user startup-shortcut setup / teardown |
| `build.ps1` | PNG snapshot for README (Pillow) |

## Runtime locations
- Installed widget: `%LOCALAPPDATA%\TrafficLightWidget\TrafficLightWidget.py`
- Startup shortcut: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Traffic Light Widget.lnk`
- Widget state: `~/.config/traffic-light-widget/state.json` (position + backend choice)
- Data source (opencode): `~/.local/share/opencode/log/opencode.log`
- Data source (Copilot): `~/.copilot/session-state/<session>/events.jsonl`

## Conventions
- No comments in source unless explicitly requested.
- No network calls, no credentials read, no telemetry.
- Keep the widget dependency-free (stdlib only) — Pillow stays optional, build-only.
- Magic transparent color `#F0ABCD` must never appear in the card art (used for `-transparentcolor`).

## Verification checklist
1. `python -c "import TrafficLightWidget as T; print(T.compute_opencode(T.time.time()))"` — returns a LightState reflecting your current opencode session.
2. `python -c "import TrafficLightWidget as T; print(T.compute_copilot(T.time.time()))"` — returns a LightState reflecting current Copilot Chat session (or idle).
3. Non-blocking render check prints `RENDER OK <width> <height>`.
4. After `install.ps1`, a `pythonw.exe` process matching `*TrafficLightWidget.py*` is running.
5. `uninstall.ps1` leaves `~/.local/share/opencode/log` and `~/.copilot/session-state` untouched.
