"""Where things live.

* User data (settings, leads, uploads, logs, Chrome profile) lives in the data dir, which is
  NEVER inside the install dir: ``OUTREACH_DATA_DIR`` env var, else ``%APPDATA%\\LeadOutreach`` on
  Windows, else ``~/.lead_outreach``.
* Read-only resources shipped with the app (web UI, user-agent list) are found with
  :func:`resource_path`, which also works inside a PyInstaller bundle (``sys._MEIPASS``).
  PyInstaller must bundle them under ``app/`` (e.g. ``--add-data app/web:app/web`` and
  ``--add-data app/resources:app/resources``).
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

APP_FOLDER_NAME = "LeadOutreach"


def _package_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass) / "app"
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """Absolute path of a read-only resource inside the ``app`` package."""
    return _package_dir().joinpath(*parts)


def web_dir() -> Path:
    return resource_path("web")


def data_dir() -> Path:
    """Resolve (and create) the user data directory. Re-evaluated on every call."""
    env = os.environ.get("OUTREACH_DATA_DIR", "").strip()
    if env:
        base = Path(env).expanduser()
    elif os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / APP_FOLDER_NAME
    else:
        base = Path.home() / ".lead_outreach"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str, is_dir: bool = False) -> Path:
    path = data_dir() / name
    if is_dir:
        path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return _sub("settings.json")


def uploads_dir() -> Path:
    return _sub("uploads", is_dir=True)


def leads_file() -> Path:
    return _sub("leads.json")


def sent_log_file() -> Path:
    return _sub("sent_log.txt")


def suppression_file() -> Path:
    return _sub("suppression.txt")


def logs_dir() -> Path:
    return _sub("logs", is_dir=True)


def app_log_file() -> Path:
    return logs_dir() / "app.log"


def chrome_profile_dir() -> Path:
    return _sub("chrome_profile", is_dir=True)


def atomic_write_text(path: Path, text: str) -> None:
    """Write a file so that a crash leaves either the old or the new content, never half."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
