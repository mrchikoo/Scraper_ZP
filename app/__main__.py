"""Start Lead Outreach: ``python -m app``.

Environment:
  OUTREACH_HOST        bind address (default 127.0.0.1; Docker sets 0.0.0.0 inside the container)
  OUTREACH_PORT        port (default 8765)
  OUTREACH_DATA_DIR    where settings, leads and logs are kept
  OUTREACH_NO_BROWSER  set to 1 to not open the browser automatically
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import urllib.request
import webbrowser

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as resp:
            return bool(json.loads(resp.read().decode("utf-8")).get("ok"))
    except Exception:
        return False


def main() -> None:
    host = os.environ.get("OUTREACH_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    try:
        port = int(os.environ.get("OUTREACH_PORT", DEFAULT_PORT))
    except ValueError:
        port = DEFAULT_PORT
    open_browser = os.environ.get("OUTREACH_NO_BROWSER", "").strip() not in ("1", "true", "yes")
    browse_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    url = f"http://{browse_host}:{port}/"

    if _already_running(port):
        print(f"Lead Outreach is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return

    from waitress import create_server

    from . import paths
    from .server import create_app, setup_logging

    setup_logging()
    log = logging.getLogger("outreach")

    def shutdown():
        # The runner has already been stopped and waited for; data files are written
        # atomically, so exiting the process here is safe.
        log.info("Shutting down on request")
        logging.shutdown()
        sys.stdout.flush()
        os._exit(0)

    app = create_app(shutdown=shutdown)
    try:
        server = create_server(app, host=host, port=port, threads=8)
    except OSError:
        print(f"Port {port} is busy. Close the other program using it, or set OUTREACH_PORT to another number.")
        sys.exit(1)

    log.info("Lead Outreach started on %s (data dir %s)", url, paths.data_dir())
    print(f"Lead Outreach is running at {url}")
    print(f"Your data is stored in {paths.data_dir()}")
    print("Keep this window open while you use the app. Close it to quit.", flush=True)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        runner = app.extensions.get("outreach_runner")
        if runner is not None:
            runner.stop()


if __name__ == "__main__":
    main()
