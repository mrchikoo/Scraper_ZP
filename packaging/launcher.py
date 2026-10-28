"""Lead Outreach desktop launcher (PyInstaller entry point).

What it does, in order:
  1. Works out the data folder (same rules as app/paths.py) and sends all
     output to <data>/logs/launcher.log (a windowed .exe has no console).
  2. If Lead Outreach is already running on the port, just opens the browser
     on it and exits.
  3. If the port is taken by some other program, shows a friendly error box.
  4. If Google Chrome is not installed, shows a box with the download link.
  5. Starts the server (app.__main__.main) and opens the browser once
     /api/health answers.

Environment switches (all optional):
  OUTREACH_PORT        port, default 8765
  OUTREACH_HOST        bind address, default 127.0.0.1
  OUTREACH_DATA_DIR    data folder override
  OUTREACH_NO_BROWSER  "1" = never open a browser (CI smoke test, Docker)
  OUTREACH_NO_DIALOGS  "1" = never show message boxes, only log (CI)

Also runnable from source for testing:  python packaging/launcher.py
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import multiprocessing
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

APP_TITLE = "Lead Outreach"
CHROME_DOWNLOAD_URL = "https://www.google.com/chrome/"
DEFAULT_PORT = 8765
HEALTH_TIMEOUT_S = 90

log = logging.getLogger("outreach.launcher")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def data_dir() -> Path:
    """Mirror of the contract in ARCHITECTURE.md (app/paths.py is the source of truth)."""
    env = os.environ.get("OUTREACH_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    appdata = os.environ.get("APPDATA")
    if sys.platform.startswith("win") and appdata:
        return Path(appdata) / "LeadOutreach"
    return Path.home() / ".lead_outreach"


def get_port() -> int:
    try:
        port = int(os.environ.get("OUTREACH_PORT", DEFAULT_PORT))
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    return DEFAULT_PORT


def get_host() -> str:
    return os.environ.get("OUTREACH_HOST", "").strip() or "127.0.0.1"


def browser_url(port: int) -> str:
    # Even if the server binds 0.0.0.0, the user's browser should use loopback.
    return f"http://127.0.0.1:{port}/"


def setup_logging(ddir: Path) -> Path:
    logs = ddir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_file = logs / "launcher.log"
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # A windowed (no-console) PyInstaller exe has sys.stdout/sys.stderr = None,
    # which makes print() and some libraries crash. Send them to the log file.
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        stream = open(logs / "console.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None or getattr(sys, "frozen", False):
            sys.stdout = stream
        if sys.stderr is None or getattr(sys, "frozen", False):
            sys.stderr = stream
    else:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(console)
    return log_file


def message_box(text: str, title: str = APP_TITLE, kind: str = "error", ask: bool = False) -> bool:
    """Show a native message box. Returns True if the user clicked Yes/OK.

    kind: "error" | "warning" | "info". ask=True shows Yes/No buttons.
    Never raises; falls back to logging when no GUI is available.
    """
    log.log(logging.ERROR if kind == "error" else logging.WARNING, "Dialog: %s", text.replace("\n", " | "))
    if _flag("OUTREACH_NO_DIALOGS"):
        return False
    try:
        if sys.platform.startswith("win"):
            import ctypes

            icon = {"error": 0x10, "warning": 0x30, "info": 0x40}.get(kind, 0x40)
            buttons = 0x04 if ask else 0x00  # MB_YESNO / MB_OK
            flags = icon | buttons | 0x00010000 | 0x00040000  # MB_SETFOREGROUND | MB_TOPMOST
            result = ctypes.windll.user32.MessageBoxW(None, text, title, flags)
            return result in (1, 6)  # IDOK / IDYES
    except Exception:  # pragma: no cover - best effort
        log.exception("Native MessageBox failed")
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if ask:
            answer = messagebox.askyesno(title, text, parent=root)
        else:
            {"error": messagebox.showerror, "warning": messagebox.showwarning}.get(
                kind, messagebox.showinfo
            )(title, text, parent=root)
            answer = True
        root.destroy()
        return bool(answer)
    except Exception:  # pragma: no cover - headless machine
        print(f"[{title}] {text}", file=sys.stderr)
        return False


def health(port: int, timeout: float = 1.5) -> dict | None:
    """Return the /api/health JSON if a Lead Outreach server answers on the port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8", "replace"))
            if isinstance(data, dict) and data.get("ok") is True:
                return data
    except Exception:
        return None
    return None


def port_is_free(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform.startswith("win") and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def find_chrome() -> str | None:
    """Best-effort search for an installed Google Chrome / Chromium."""
    for env_name in ("OUTREACH_CHROME_BINARY", "CHROME_BIN"):
        p = os.environ.get(env_name)
        if p and Path(p).is_file():
            return p
    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        try:
            import winreg

            sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, sub) as key:
                        value, _ = winreg.QueryValueEx(key, None)
                        if value:
                            candidates.append(Path(value.strip('"')))
                except OSError:
                    pass
        except ImportError:
            pass
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432"):
            base = os.environ.get(env_name)
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates += [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    else:
        import shutil

        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def _is_port_error(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and getattr(exc, "errno", None) in (48, 98, 10013, 10048)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ddir = data_dir()
    try:
        log_file = setup_logging(ddir)
    except Exception:
        message_box(
            f"Lead Outreach could not create its data folder:\n{ddir}\n\n"
            "Please check that your user account can write there and try again.",
        )
        return 1

    # Make sure the backend uses exactly the same folder and port.
    os.environ["OUTREACH_DATA_DIR"] = str(ddir)
    port = get_port()
    host = get_host()
    os.environ["OUTREACH_PORT"] = str(port)
    os.environ["OUTREACH_HOST"] = host
    log.info("Starting %s (frozen=%s) data=%s host=%s port=%s",
             APP_TITLE, getattr(sys, "frozen", False), ddir, host, port)

    # 1. Already running? Just show it again.
    if health(port):
        log.info("Already running; reopening the browser")
        if not _flag("OUTREACH_NO_BROWSER"):
            webbrowser.open(browser_url(port), new=2)
        return 0

    # 2. Port used by something else?
    if not port_is_free(host, port):
        message_box(
            f"Lead Outreach could not start because another program is already using "
            f"port {port} on this computer.\n\n"
            "What to try:\n"
            "  1. Restart your computer, then open Lead Outreach again.\n"
            "  2. If that does not help, ask your helper to change the port "
            "(setting OUTREACH_PORT).",
        )
        return 2

    # 3. Chrome present? (Needed for finding businesses, not for the settings pages.)
    if not find_chrome():
        if message_box(
            "Google Chrome is not installed on this computer.\n\n"
            "Lead Outreach needs Google Chrome to search for businesses. "
            "Your settings will still open, but searching will not work until Chrome is installed.\n\n"
            f"Open the Chrome download page now?\n{CHROME_DOWNLOAD_URL}",
            kind="warning",
            ask=True,
        ):
            webbrowser.open(CHROME_DOWNLOAD_URL, new=2)

    # 4. Start the server (blocks) and open the browser from a helper thread.
    launcher_wants_browser = not _flag("OUTREACH_NO_BROWSER")
    # The backend must not open a second tab: the launcher opens it once the server is healthy.
    os.environ["OUTREACH_NO_BROWSER"] = "1"
    stop = threading.Event()
    if launcher_wants_browser:
        t = threading.Thread(target=_open_after_start, args=(port, stop), daemon=True)
        t.start()

    try:
        run_server()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        log.info("Server exited with code %s", code)
        stop.set()
        return code
    except BaseException as exc:  # noqa: BLE001 - we want a dialog for anything
        stop.set()
        log.error("Server crashed:\n%s", traceback.format_exc())
        if _is_port_error(exc):
            message_box(
                f"Lead Outreach could not use port {port} because another program took it.\n\n"
                "Please restart your computer and open Lead Outreach again.",
            )
            return 2
        message_box(
            "Sorry, Lead Outreach stopped unexpectedly.\n\n"
            "Please send the files in this folder to your helper so they can see what went wrong:\n"
            f"{log_file.parent}",
        )
        return 1
    stop.set()
    return 0


def _open_after_start(port: int, stop: threading.Event) -> None:
    # OUTREACH_NO_BROWSER was forced to 1 for the backend; the launcher still opens it here.
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline and not stop.is_set():
        if health(port, timeout=1.0):
            log.info("Server is up; opening %s", browser_url(port))
            webbrowser.open(browser_url(port), new=2)
            return
        time.sleep(0.5)
    if not stop.is_set():
        log.error("Server did not answer /api/health within %ss", HEALTH_TIMEOUT_S)


def run_server() -> None:
    """Start the backend exactly like `python -m app` would.

    Preferred contract: app/__main__.py defines main() and guards the call with
    `if __name__ == "__main__": main()`. Fallback: run the module via runpy.
    """
    try:
        from app.__main__ import main as app_main  # type: ignore
    except ImportError:
        app_main = None
    if callable(app_main):
        app_main()
        return
    import runpy

    runpy.run_module("app", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    # When run from source (python packaging/launcher.py) make `import app` work.
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(main())
