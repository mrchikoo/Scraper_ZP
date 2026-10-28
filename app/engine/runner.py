"""Background run orchestration (port of the old run_areas.py).

One scraper thread walks through every (business type x area) search; one sender thread
emails new leads as they appear, with random pauses, a rolling-24h daily cap, a per-domain cap
and the suppression list. Stopping sets a flag; both threads finish their current step and exit.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque

from .. import paths, settings as settings_mod
from . import areas, filters, sender
from .leads import LeadStore
from .scraper import MapsScraper, StopRequested, find_chrome

log = logging.getLogger("outreach.run")

LOG_BUFFER = 2000
MAX_CONSECUTIVE_SEND_FAILURES = 5
IDLE_POLL_S = 20


class LogBuffer:
    """Ring buffer of plain-English lines with a running sequence number."""

    def __init__(self, size: int = LOG_BUFFER):
        self._lines: deque[str] = deque(maxlen=size)
        self._next = 0
        self._lock = threading.Lock()

    def add(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        with self._lock:
            self._lines.append(line)
            self._next += 1
        log.info(message)

    def since(self, since: int) -> dict:
        with self._lock:
            first = self._next - len(self._lines)
            if since < 0 or since > self._next:
                since = first  # client is from an earlier app session: send everything
            start = max(since, first)
            lines = list(self._lines)[start - first:]
            return {"next": self._next, "lines": lines}


class Runner:
    def __init__(self, store: LeadStore | None = None, smtp_factory=None, scraper_factory=None):
        self.store = store or LeadStore()
        self.logs = LogBuffer()
        self._smtp_factory = smtp_factory
        self._scraper_factory = scraper_factory
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._scrape_done = threading.Event()
        self.state = "idle"
        self.mode = None
        self.current_area = ""
        self.areas_done = 0
        self.areas_total = 0
        self.last_error = None

    # ------------------------------------------------------------------ public API
    def status(self) -> dict:
        cfg = settings_mod.load()
        with self._lock:
            return {
                "state": self.state,
                "mode": self.mode,
                "current_area": self.current_area,
                "areas_done": self.areas_done,
                "areas_total": self.areas_total,
                "leads_found": self.store.count(),
                "sent_total": self.store.sent_total(),
                "sent_today": self.store.sent_last_24h(),
                "daily_cap": settings_mod.effective_daily_cap(cfg),
                "last_error": self.last_error,
            }

    def start(self, mode: str) -> tuple[bool, str]:
        if mode not in ("scrape", "send", "both"):
            return False, "Please choose what to do: find businesses, send emails, or both."
        with self._lock:
            if self.state != "idle":
                return False, "It is already running. Press Stop first if you want to start again."
            cfg = settings_mod.load()
            missing = settings_mod.missing_for(cfg, mode)
            if missing:
                return False, "Before starting, please fill in: " + "; ".join(missing) + "."
            if mode in ("scrape", "both") and not find_chrome() and not self._scraper_factory:
                return False, ("Google Chrome was not found on this computer. Please install Google "
                               "Chrome (google.com/chrome), then try again.")
            if mode in ("send", "both"):
                cap = settings_mod.effective_daily_cap(cfg)
                if self.store.sent_last_24h() >= cap and mode == "send":
                    return False, (f"You have already sent {cap} emails in the last 24 hours (your daily "
                                   "limit). Please try again later.")
            self._stop.clear()
            self._scrape_done.clear()
            self.state, self.mode, self.last_error = "running", mode, None
            self.current_area, self.areas_done, self.areas_total = "", 0, 0
            self.store.reload()
            self._threads = []
            if mode in ("scrape", "both"):
                self._threads.append(threading.Thread(target=self._scrape_thread, args=(cfg,), name="scraper", daemon=True))
            else:
                self._scrape_done.set()
            if mode in ("send", "both"):
                self._threads.append(threading.Thread(target=self._send_thread, name="sender", daemon=True))
            for t in self._threads:
                t.start()
            threading.Thread(target=self._watch, name="run-watch", daemon=True).start()
        labels = {"scrape": "Finding businesses", "send": "Sending emails",
                  "both": "Finding businesses and sending emails"}
        self.logs.add(f"Started: {labels[mode]}.")
        return True, f"Started. {labels[mode]}... You can follow the progress below."

    def stop(self) -> None:
        with self._lock:
            if self.state == "running":
                self.state = "stopping"
                self._stop.set()
                self.logs.add("Stopping... finishing the current step, this can take up to a minute.")

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.time() + timeout
        while True:
            with self._lock:
                if self.state == "idle":
                    return True
            if deadline is not None and time.time() > deadline:
                return False
            time.sleep(0.05)

    # ------------------------------------------------------------------ internals
    def _watch(self):
        for t in list(self._threads):
            t.join()
        with self._lock:
            stopped = self._stop.is_set()
            self.state = "idle"
            self.current_area = ""
        self.logs.add("Stopped." if stopped else "All done.")

    def _error(self, message: str):
        with self._lock:
            self.last_error = message
        self.logs.add(message)

    def _searches(self, cfg) -> list[tuple[str, dict, tuple]]:
        target = cfg["targeting"]
        out = []
        for key in target["business_types"]:
            bt = areas.business_type(key)
            for area_name in target["areas"]:
                area = areas.find_area(area_name, target.get("city", ""))
                search_key = f"{bt['query']}|{area[0]}|{target.get('city', '')}".lower()
                out.append((search_key, bt, area))
        return out

    def _scrape_thread(self, cfg):
        scraper = None
        try:
            city = cfg["targeting"].get("city", "")
            country = cfg["targeting"].get("country", "")
            searches = self._searches(cfg)
            keys = [s[0] for s in searches]
            if keys and all(self.store.search_done(k) for k in keys):
                self.logs.add("All the chosen areas were searched before; searching them again for new businesses.")
                self.store.clear_searches(keys)
            with self._lock:
                self.areas_total = len(searches)
            factory = self._scraper_factory or MapsScraper
            scraper = factory(self._stop, self.logs.add, self.store)
            scraper.segment = cfg["targeting"].get("segment", "any")
            if scraper.segment != "any":
                self.logs.add("Business size filter: " + ("small businesses only" if scraper.segment == "small" else "mid-sized / established businesses only") + ".")
            failures_in_a_row = 0
            for key, bt, (area_name, lat, lng) in searches:
                if self._stop.is_set():
                    break
                label = f"{bt['label']} in {area_name}"
                with self._lock:
                    self.current_area = label
                if self.store.search_done(key):
                    self.logs.add(f"{label}: already searched earlier, skipping.")
                    with self._lock:
                        self.areas_done += 1
                    continue
                self.logs.add(f"Searching Google Maps: {label}...")
                url = areas.maps_search_url(bt["query"], area_name, city, lat, lng, country=country)

                def on_lead(email, name, website, _area=area_name, _bt=bt["key"]):
                    return self.store.add_lead(email, name, website, _area, _bt)

                try:
                    count = scraper.scrape_search(url, on_lead)
                    failures_in_a_row = 0
                    self.store.mark_search_done(key)
                    self.logs.add(f"Finished {label}: looked at {count} businesses. "
                                  f"{self.store.count()} emails in your list so far.")
                except StopRequested:
                    break
                except Exception as exc:  # browser crashed, network down, ...
                    failures_in_a_row += 1
                    log.exception("scrape failed for %s", label)
                    self._error(f"Searching {label} did not work ({type(exc).__name__}). Moving on.")
                    scraper.close()
                    if failures_in_a_row >= 3:
                        self._error("Searching keeps failing. Please check your internet connection and "
                                    "that Google Chrome is installed, then start again.")
                        break
                with self._lock:
                    self.areas_done += 1
        except Exception as exc:
            log.exception("scraper thread crashed")
            msg = str(exc).lower()
            if "chrome" in msg and ("binary" in msg or "not found" in msg or "cannot find" in msg):
                self._error("Google Chrome could not be started. Please install or update Google Chrome.")
            else:
                self._error(f"Finding businesses stopped because of an unexpected problem ({type(exc).__name__}).")
        finally:
            if scraper is not None:
                scraper.close()
            self._scrape_done.set()

    def _send_thread(self):
        gmail = None
        failures = 0
        try:
            while not self._stop.is_set():
                cfg = settings_mod.load()
                lim = cfg["limits"]
                cap = settings_mod.effective_daily_cap(cfg)
                if self.store.sent_last_24h() >= cap:
                    self.logs.add(f"Daily limit reached ({cap} emails in 24 hours). Sending will pause; "
                                  "start again tomorrow to continue.")
                    break
                lead = self.store.next_pending(int(lim.get("max_per_domain", 2)))
                if lead is None:
                    if self._scrape_done.is_set():
                        self.logs.add("No more new emails to send right now.")
                        break
                    self._stop.wait(IDLE_POLL_S)
                    continue
                if gmail is None:
                    gmail = sender.GmailSender(cfg["smtp"]["email"], cfg["smtp"]["app_password"], self._smtp_factory)
                email = lead["email"]
                rendered = sender.render_email(cfg["email"]["subject"], cfg["email"]["body"],
                                               cfg["profile"], lead.get("business_name"))
                files = [paths.uploads_dir() / name for name in cfg["email"].get("attachments", [])]
                missing = [f.name for f in files if not f.is_file()]
                if missing:
                    self._error("An attachment is missing (" + ", ".join(missing) + "). Please upload it again "
                                "in 'Your email'. Sending is paused.")
                    break
                msg = sender.build_message(cfg["smtp"]["email"], cfg["profile"].get("full_name", ""),
                                           email, rendered, files)
                self.store.mark_attempt(email)
                try:
                    gmail.send(msg)
                except sender.SendError as err:
                    self.store.mark_failed(email, err.message)
                    if err.fatal:
                        self._error(err.message)
                        break
                    failures += 1
                    self.logs.add(f"Could not send to {email}: {err.message}")
                    if failures >= MAX_CONSECUTIVE_SEND_FAILURES:
                        self._error("Several emails in a row could not be sent, so sending is paused. "
                                    "Please check your internet connection and use 'Test connection'.")
                        break
                    self._stop.wait(30)
                    continue
                failures = 0
                self.store.mark_sent(email)
                self.logs.add(f"Sent to {email}" + (f" ({lead['business_name']})" if lead.get("business_name") else "")
                              + f". {self.store.sent_last_24h()}/{cap} in the last 24 hours.")
                lo = max(1, int(lim.get("min_delay_s", 45)))
                hi = max(lo, int(lim.get("max_delay_s", 150)))
                if self._stop.wait(random.uniform(lo, hi)):
                    break
        except Exception as exc:
            log.exception("sender thread crashed")
            self._error(f"Sending stopped because of an unexpected problem ({type(exc).__name__}).")
        finally:
            if gmail is not None:
                gmail.close()


def send_test_email(cfg: dict, store: LeadStore | None = None, smtp_factory=None) -> tuple[bool, str]:
    """Send the current email to the user's own address."""
    to = cfg["smtp"].get("email")
    if not to or not cfg["smtp"].get("app_password"):
        return False, "Please enter and save your Gmail address and App Password first (in 'Gmail connection')."
    if not cfg["email"].get("subject", "").strip() or not cfg["email"].get("body", "").strip():
        return False, "Please write a subject and the email text first."
    rendered = sender.render_email(cfg["email"]["subject"], cfg["email"]["body"], cfg["profile"], "Sunrise Cafe")
    rendered["subject"] = "[Test] " + rendered["subject"]
    files = [paths.uploads_dir() / n for n in cfg["email"].get("attachments", [])]
    msg = sender.build_message(to, cfg["profile"].get("full_name", ""), to, rendered, files)
    gmail = sender.GmailSender(to, cfg["smtp"]["app_password"], smtp_factory)
    try:
        gmail.send(msg)
    except sender.SendError as err:
        return False, err.message
    finally:
        gmail.close()
    if store is not None:
        store.record_external_send(to)
    return True, (f"Test email sent to {to}. Check your inbox (the business name shows as "
                  "'Sunrise Cafe' as an example).")


__all__ = ["Runner", "LogBuffer", "send_test_email", "filters"]
