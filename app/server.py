"""Flask app exposing the JSON API under /api and serving the static UI from app/web."""
from __future__ import annotations

import logging
import os
import re
import threading
from logging.handlers import RotatingFileHandler

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.utils import secure_filename

from . import __version__, paths, settings as settings_mod
from .engine import areas, sender
from .engine.leads import LeadStore
from .engine.runner import Runner, send_test_email
from .engine.scraper import find_chrome

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

log = logging.getLogger("outreach")


# ----------------------------------------------------------------------------- logging
class SecretRedactingFilter(logging.Filter):
    """Belt and braces: blank out the stored App Password if it ever reaches a log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            secret = settings_mod.load()["smtp"].get("app_password")
        except Exception:
            secret = None
        if secret:
            msg = record.getMessage()
            if secret in msg:
                record.msg = msg.replace(secret, "********")
                record.args = None
        return True


_logging_configured = False


def setup_logging() -> None:
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True
    handler = RotatingFileHandler(paths.app_log_file(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(SecretRedactingFilter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for noisy in ("urllib3", "selenium", "waitress.queue"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ----------------------------------------------------------------------------- app
def create_app(runner: Runner | None = None, smtp_factory=None, shutdown=None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 512 * 1024
    app.config["JSON_SORT_KEYS"] = False
    runner = runner or Runner(LeadStore(), smtp_factory=smtp_factory)
    app.extensions["outreach_runner"] = runner
    store = runner.store

    def fail(message: str):
        return jsonify({"ok": False, "message": message})

    def body() -> dict:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    @app.after_request
    def no_cache(resp):
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ------------------------------------------------------------------ health / settings
    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "version": __version__, "chrome_found": bool(find_chrome()),
                        "data_dir": str(paths.data_dir())})

    @app.get("/api/settings")
    def get_settings():
        return jsonify(settings_mod.public_view(settings_mod.load()))

    @app.put("/api/settings")
    def put_settings():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"ok": False, "errors": {"_": "The settings could not be read. Please try again."}})
        data = dict(data)
        if isinstance(data.get("email"), dict):
            # Attachments are managed only through /api/attachments.
            data["email"] = {k: v for k, v in data["email"].items() if k != "attachments"}
        _, errors = settings_mod.update(data)
        return jsonify({"ok": not errors, "errors": errors})

    # ------------------------------------------------------------------ smtp / email
    @app.post("/api/smtp/test")
    def smtp_test():
        cfg = settings_mod.load()
        ok, message = sender.test_login(cfg["smtp"].get("email"), cfg["smtp"].get("app_password"), smtp_factory)
        return jsonify({"ok": ok, "message": message})

    @app.post("/api/email/preview")
    def email_preview():
        data = body()
        cfg = settings_mod.load()
        subject = data.get("subject")
        text = data.get("body")
        rendered = sender.render_email(
            cfg["email"]["subject"] if subject is None else str(subject),
            cfg["email"]["body"] if text is None else str(text),
            cfg["profile"],
            str(data.get("business_name") or "") or None,
        )
        return jsonify(rendered)

    @app.post("/api/email/test-send")
    def email_test_send():
        ok, message = send_test_email(settings_mod.load(), store, smtp_factory)
        return jsonify({"ok": ok, "message": message})

    # ------------------------------------------------------------------ attachments
    def _attachment_list():
        files = sorted(paths.uploads_dir().glob("*.pdf"), key=lambda p: p.name.lower())
        return [{"name": p.name, "size": p.stat().st_size} for p in files]

    @app.get("/api/attachments")
    def list_attachments():
        return jsonify(_attachment_list())

    @app.post("/api/attachments")
    def upload_attachment():
        f = request.files.get("file")
        if f is None or not f.filename:
            return fail("Please choose a PDF file to upload.")
        name = secure_filename(f.filename) or "attachment.pdf"
        if not name.lower().endswith(".pdf"):
            return fail("Only PDF files can be attached. Please save your file as a PDF first.")
        name = name[:-4] + ".pdf"
        data = f.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return fail("That file is bigger than 10 MB. Please make it smaller and try again.")
        if not data.startswith(b"%PDF"):
            return fail("That file does not look like a real PDF. Please export it as PDF and try again.")
        paths.atomic_write_bytes(paths.uploads_dir() / name, data)
        cfg = settings_mod.load()
        current = list(cfg["email"].get("attachments", []))
        if name not in current:
            settings_mod.update({"email": {"attachments": current + [name]}})
        return jsonify({"ok": True, "name": name})

    @app.delete("/api/attachments/<path:name>")
    def delete_attachment(name):
        safe = secure_filename(name)
        target = paths.uploads_dir() / safe
        if not safe or not target.is_file():
            return fail("That file was not found. It may already have been removed.")
        target.unlink()
        cfg = settings_mod.load()
        settings_mod.update({"email": {"attachments": [n for n in cfg["email"].get("attachments", []) if n != safe]}})
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ areas / run
    @app.get("/api/areas")
    def get_areas():
        # ?city=Pune looks that place up; with no city, the saved one is used (nothing if none is saved yet).
        city = (request.args.get("city") or settings_mod.load()["targeting"].get("city") or "").strip()[:80]
        found = areas.localities(city)
        return jsonify({**found, "business_types": areas.business_type_presets()})

    @app.post("/api/run/start")
    def run_start():
        ok, message = runner.start(str(body().get("mode") or "both"))
        return jsonify({"ok": ok, "message": message})

    @app.post("/api/run/stop")
    def run_stop():
        runner.stop()
        return jsonify({"ok": True})

    @app.get("/api/run/status")
    def run_status():
        return jsonify(runner.status())

    @app.get("/api/run/logs")
    def run_logs():
        try:
            since = int(request.args.get("since", "0"))
        except ValueError:
            since = 0
        return jsonify(runner.logs.since(since))

    # ------------------------------------------------------------------ leads
    @app.get("/api/leads")
    def get_leads():
        return jsonify(store.list_leads())

    @app.post("/api/leads/exclude")
    def exclude_lead():
        email = str(body().get("email") or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return fail("Please give a valid email address to exclude.")
        store.suppress(email)
        log.info("Address added to the do-not-email list")
        return jsonify({"ok": True, "message": f"{email} will never be emailed."})

    @app.get("/api/leads/export.csv")
    def export_leads():
        csv_text = "﻿" + store.export_csv()  # BOM so Excel opens it as UTF-8
        return Response(csv_text, mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=leads.csv"})

    # ------------------------------------------------------------------ app control
    @app.post("/api/app/quit")
    def app_quit():
        runner.stop()

        def _later():
            runner.wait(timeout=60)
            if shutdown:
                shutdown()
            else:
                os._exit(0)

        if shutdown is not False:
            threading.Timer(0.5, _later).start()
        return jsonify({"ok": True})

    @app.route("/api/<path:_unused>", methods=["GET", "POST", "PUT", "DELETE"])
    def api_not_found(_unused):
        return jsonify({"ok": False, "message": "Unknown address."}), 404

    # ------------------------------------------------------------------ errors
    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc):
        return fail("That file is bigger than 10 MB. Please make it smaller and try again.")

    @app.errorhandler(Exception)
    def unexpected(exc):
        if isinstance(exc, HTTPException):
            return exc
        log.exception("Unhandled error on %s", request.path)
        return jsonify({"ok": False, "message": "Something went wrong inside the app. Please try again; "
                                                "if it keeps happening, restart the app."}), 500

    # ------------------------------------------------------------------ static UI
    @app.get("/")
    def index():
        web = paths.web_dir()
        if (web / "index.html").is_file():
            return send_from_directory(web, "index.html")
        return Response("<!doctype html><meta charset=utf-8><title>Lead Outreach</title>"
                        "<p style='font-family:sans-serif'>Lead Outreach is running, but its screen files "
                        "are missing. Please reinstall the app.</p>", mimetype="text/html")

    @app.get("/<path:filename>")
    def static_files(filename):
        web = paths.web_dir()
        if not web.is_dir():
            return Response("Not found", status=404, mimetype="text/plain")
        return send_from_directory(web, filename)

    return app
