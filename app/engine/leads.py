"""Leads store, sent log and suppression list.

* ``leads.json``  - every address found (+ business name, website, area), the websites already
  scanned and the searches already completed. Written atomically after every change.
* ``sent_log.txt`` - append-only, fsync'ed. One line per event: ``email<TAB>iso-time<TAB>event``
  where event is ``attempt`` (written BEFORE handing the email to Gmail), ``sent`` or ``failed``.
  An ``attempt`` without a later ``sent``/``failed`` (e.g. the app crashed mid-send) is treated
  as sent, so a crash or restart can never email the same address twice.
* ``suppression.txt`` - addresses (or ``@domain``) that must never be emailed.
"""
from __future__ import annotations

import csv
import io
import json
import os
import threading
from datetime import datetime, timedelta, timezone

from .. import paths
from . import filters

MAX_SEND_ATTEMPTS = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class LeadStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._leads: dict[str, dict] = {}
        self._websites: set[str] = set()
        self._done_searches: set[str] = set()
        self._sent: dict[str, str] = {}       # email -> sent_at (iso)
        self._send_times: list[datetime] = []  # for the rolling 24h cap
        self._suppressed: set[str] = set()
        self.reload()

    # ------------------------------------------------------------------ persistence
    def reload(self) -> None:
        with self._lock:
            self._leads, self._websites, self._done_searches = {}, set(), set()
            path = paths.leads_file()
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8")) or {}
                    self._leads = {k.lower(): v for k, v in (data.get("leads") or {}).items()}
                    self._websites = set(data.get("websites") or [])
                    self._done_searches = set(data.get("done_searches") or [])
                except (OSError, ValueError):
                    # Keep the broken file for inspection instead of overwriting it silently.
                    try:
                        os.replace(path, path.with_suffix(".broken.json"))
                    except OSError:
                        pass
            self._load_sent_log()
            self._load_suppression()

    def _load_sent_log(self) -> None:
        self._sent, self._send_times = {}, []
        pending: dict[str, str] = {}
        path = paths.sent_log_file()
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                email = parts[0].strip().lower()
                if not email:
                    continue
                when = parts[1] if len(parts) > 1 else ""
                event = parts[2].strip() if len(parts) > 2 else "sent"
                if event == "attempt":
                    pending[email] = when
                elif event == "sent":
                    pending.pop(email, None)
                    self._sent[email] = when
                    if (dt := _parse(when)):
                        self._send_times.append(dt)
                elif event == "failed":
                    pending.pop(email, None)
        for email, when in pending.items():  # crashed mid-send: never retry
            self._sent.setdefault(email, when)
            if (dt := _parse(when)):
                self._send_times.append(dt)

    def _load_suppression(self) -> None:
        path = paths.suppression_file()
        self._suppressed = set()
        if path.exists():
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                self._suppressed = {ln.strip().lower() for ln in f if ln.strip() and not ln.startswith("#")}

    def _save(self) -> None:
        data = {
            "version": 1,
            "leads": self._leads,
            "websites": sorted(self._websites),
            "done_searches": sorted(self._done_searches),
        }
        paths.atomic_write_text(paths.leads_file(), json.dumps(data, indent=1, ensure_ascii=False))

    def _append_sent_log(self, email: str, event: str, when: datetime) -> None:
        with open(paths.sent_log_file(), "a", encoding="utf-8") as f:
            f.write(f"{email}\t{_iso(when)}\t{event}\n")
            f.flush()
            os.fsync(f.fileno())

    # ------------------------------------------------------------------ websites / searches
    def website_seen(self, domain: str) -> bool:
        with self._lock:
            return domain.lower() in self._websites

    def mark_website(self, domain: str) -> None:
        with self._lock:
            self._websites.add(domain.lower())
            self._save()

    def search_done(self, key: str) -> bool:
        with self._lock:
            return key in self._done_searches

    def mark_search_done(self, key: str) -> None:
        with self._lock:
            self._done_searches.add(key)
            self._save()

    def clear_searches(self, keys) -> None:
        with self._lock:
            self._done_searches.difference_update(keys)
            self._save()

    # ------------------------------------------------------------------ leads
    def add_lead(self, email: str, business_name: str = "", website: str = "", area: str = "",
                 business_type: str = "") -> bool:
        """Store a new address. Returns False if it was already known."""
        email = (email or "").strip().lower()
        if not email:
            return False
        with self._lock:
            if email in self._leads:
                return False
            self._leads[email] = {
                "email": email,
                "business_name": business_name or "",
                "website": website or "",
                "area": area or "",
                "business_type": business_type or "",
                "status": "new",
                "attempts": 0,
                "found_at": _iso(_now()),
            }
            self._save()
            return True

    def count(self) -> int:
        with self._lock:
            return len(self._leads)

    def get(self, email: str) -> dict | None:
        with self._lock:
            lead = self._leads.get((email or "").lower())
            return dict(lead) if lead else None

    def is_suppressed(self, email: str) -> bool:
        email = email.lower()
        with self._lock:
            return email in self._suppressed or "@" + filters.email_domain(email) in self._suppressed

    def was_sent(self, email: str) -> bool:
        with self._lock:
            return email.lower() in self._sent

    def status_of(self, lead: dict) -> str:
        email = lead["email"]
        if email in self._sent:
            return "sent"
        if self.is_suppressed(email):
            return "excluded"
        return lead.get("status", "new") if lead.get("status") in ("new", "failed") else "new"

    def list_leads(self) -> list[dict]:
        with self._lock:
            out = []
            for lead in sorted(self._leads.values(), key=lambda l: l.get("found_at", ""), reverse=True):
                status = self.status_of(lead)
                item = {
                    "email": lead["email"],
                    "business_name": lead.get("business_name", ""),
                    "website": lead.get("website", ""),
                    "area": lead.get("area", ""),
                    "status": status,
                }
                if status == "sent":
                    item["sent_at"] = self._sent.get(lead["email"]) or lead.get("sent_at", "")
                out.append(item)
            return out

    def export_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["email", "business_name", "website", "area", "business_type", "status", "sent_at", "found_at"])

        def safe(value):  # stop spreadsheet formula injection
            value = "" if value is None else str(value)
            return "'" + value if value[:1] in ("=", "+", "-", "@") else value

        with self._lock:
            for item in self.list_leads():
                raw = self._leads.get(item["email"], {})
                writer.writerow([safe(item["email"]), safe(item["business_name"]), safe(item["website"]),
                                 safe(item["area"]), safe(raw.get("business_type", "")), item["status"],
                                 item.get("sent_at", ""), raw.get("found_at", "")])
        return buf.getvalue()

    # ------------------------------------------------------------------ suppression
    def suppress(self, email: str) -> None:
        email = email.strip().lower()
        with self._lock:
            if email in self._suppressed:
                return
            self._suppressed.add(email)
            with open(paths.suppression_file(), "a", encoding="utf-8") as f:
                f.write(email + "\n")
                f.flush()
                os.fsync(f.fileno())

    # ------------------------------------------------------------------ sending
    def sent_last_24h(self) -> int:
        cutoff = _now() - timedelta(hours=24)
        with self._lock:
            self._send_times = [t for t in self._send_times if t >= cutoff]
            return len(self._send_times)

    def sent_total(self) -> int:
        with self._lock:
            return len(self._sent)

    def next_pending(self, max_per_domain: int) -> dict | None:
        """The oldest lead that may be emailed now, honouring suppression, dedupe and the
        per-domain cap (business domains only; each freemail address counts on its own)."""
        with self._lock:
            per_domain: dict[str, int] = {}
            for email in self._sent:
                d = filters.email_domain(email)
                per_domain[d] = per_domain.get(d, 0) + 1
            # One pitch per business: skip other addresses found on an already-emailed website.
            emailed_sites = {l.get("website") for e, l in self._leads.items() if e in self._sent and l.get("website")}
            for lead in sorted(self._leads.values(), key=lambda l: l.get("found_at", "")):
                email = lead["email"]
                if email in self._sent or lead.get("status") == "failed" or self.is_suppressed(email):
                    continue
                if lead.get("website") and lead["website"] in emailed_sites:
                    continue
                if not filters.is_sendable(email):
                    continue
                d = filters.email_domain(email)
                if d not in filters.FREEMAIL and per_domain.get(d, 0) >= max_per_domain:
                    continue
                return dict(lead)
            return None

    def mark_attempt(self, email: str) -> None:
        """Call immediately BEFORE handing the email to the SMTP server."""
        with self._lock:
            self._append_sent_log(email.lower(), "attempt", _now())

    def mark_sent(self, email: str) -> None:
        email = email.lower()
        now = _now()
        with self._lock:
            self._append_sent_log(email, "sent", now)
            self._sent[email] = _iso(now)
            self._send_times.append(now)
            if email in self._leads:
                self._leads[email]["status"] = "sent"
                self._leads[email]["sent_at"] = _iso(now)
                self._save()

    def mark_failed(self, email: str, reason: str = "") -> None:
        email = email.lower()
        with self._lock:
            self._append_sent_log(email, "failed", _now())
            lead = self._leads.get(email)
            if lead is not None:
                lead["attempts"] = int(lead.get("attempts", 0)) + 1
                lead["last_error"] = reason[:300]
                if lead["attempts"] >= MAX_SEND_ATTEMPTS:
                    lead["status"] = "failed"
                self._save()

    def record_external_send(self, email: str) -> None:
        """A send outside the lead list (e.g. the test email) still counts for the daily cap."""
        with self._lock:
            self._send_times.append(_now())
