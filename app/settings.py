"""settings.json: load, save (atomically), validate, and mask secrets.

The Gmail App Password is stored only in settings.json in the user's data dir. It is never
returned by the API (``public_view`` replaces it with ``has_app_password``) and never logged.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import threading

from . import paths

log = logging.getLogger(__name__)

HARD_MAX_PER_DAY = 400
DEFAULT_MAX_PER_DAY = 100

DEFAULT_SUBJECT = "Helping {{business_name}} get more customers online"
DEFAULT_BODY = """Hi {{business_name}} team,

My name is {{my_name}} from {{my_business}}. I help local businesses get more customers through social media, Google and simple, effective online marketing.

I had a look at your business and I think there is a real opportunity to bring in more enquiries. I have attached a short overview of my work.

Would you be open to a quick 10-minute call this week?

Thanks,
{{my_name}}
{{my_business}}
{{my_phone}}
{{my_website}}"""

DEFAULTS: dict = {
    "profile": {"full_name": "", "business_name": "", "phone": "", "website": "", "services": ""},
    "smtp": {"email": "", "app_password": ""},
    "email": {"subject": DEFAULT_SUBJECT, "body": DEFAULT_BODY, "attachments": []},
    "targeting": {"city": "", "country": "", "business_types": ["restaurants"], "areas": [],
                  "segment": "any"},
    "limits": {
        "max_per_day": DEFAULT_MAX_PER_DAY,
        "min_delay_s": 45,
        "max_delay_s": 150,
        "max_per_domain": 2,
    },
}

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

_lock = threading.RLock()


def normalize_app_password(value: str) -> str:
    return re.sub(r"[\s-]", "", value or "")


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load() -> dict:
    """Full settings including the secret. Never send this dict to the browser."""
    with _lock:
        path = paths.settings_file()
        stored = {}
        if path.exists():
            try:
                stored = json.loads(path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                log.warning("settings.json could not be read; using defaults")
                stored = {}
        merged = _deep_merge(DEFAULTS, {k: v for k, v in stored.items() if k in DEFAULTS})
        merged["limits"]["max_per_day"] = effective_daily_cap(merged)
        return merged


def save(settings: dict) -> None:
    with _lock:
        clean = {k: settings[k] for k in DEFAULTS if k in settings}
        paths.atomic_write_text(paths.settings_file(), json.dumps(clean, indent=2, ensure_ascii=False))


def effective_daily_cap(settings: dict) -> int:
    try:
        value = int(settings.get("limits", {}).get("max_per_day", DEFAULT_MAX_PER_DAY))
    except (TypeError, ValueError):
        value = DEFAULT_MAX_PER_DAY
    return max(1, min(HARD_MAX_PER_DAY, value))


def public_view(settings: dict) -> dict:
    """Settings safe to send to the browser: the App Password is replaced by a flag."""
    view = copy.deepcopy(settings)
    smtp = view.setdefault("smtp", {})
    has_pw = bool(smtp.pop("app_password", ""))
    smtp["has_app_password"] = has_pw
    return view


def _as_int(value, field, errors, lo, hi, message):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None  # empty box: keep the stored value
    try:
        if isinstance(value, bool):
            raise ValueError
        number = int(float(value))
    except (TypeError, ValueError):
        errors[field] = message
        return None
    return max(lo, min(hi, number))


def _str(value, limit=5000) -> str:
    return ("" if value is None else str(value)).strip()[:limit]


def update(partial: dict) -> tuple[dict, dict]:
    """Apply a full or partial settings dict. Valid fields are saved; invalid ones are
    reported in ``errors`` (field path -> plain-English message) and keep their old value.
    Returns (new_full_settings, errors)."""
    errors: dict[str, str] = {}
    if not isinstance(partial, dict):
        return load(), {"_": "The settings could not be read. Please try again."}

    with _lock:
        current = load()
        new = copy.deepcopy(current)

        profile = partial.get("profile")
        if isinstance(profile, dict):
            for key in DEFAULTS["profile"]:
                if key in profile:
                    new["profile"][key] = _str(profile[key], 2000)
            website = new["profile"]["website"]
            if website and " " in website:
                errors["profile.website"] = "The website address should not contain spaces."
                new["profile"]["website"] = current["profile"]["website"]

        smtp = partial.get("smtp")
        if isinstance(smtp, dict):
            if "email" in smtp:
                email = _str(smtp["email"], 254).lower()
                if email and not EMAIL_RE.match(email):
                    errors["smtp.email"] = "That does not look like an email address. Example: yourname@gmail.com"
                else:
                    new["smtp"]["email"] = email
            pw = normalize_app_password(_str(smtp.get("app_password"), 200))
            if pw:  # empty / omitted keeps the stored one
                if not re.fullmatch(r"[A-Za-z]{16}", pw):
                    errors["smtp.app_password"] = (
                        "A Gmail App Password is exactly 16 letters (Google shows it in 4 groups "
                        "of 4). Please copy it again from your Google account."
                    )
                else:
                    new["smtp"]["app_password"] = pw.lower()

        email_cfg = partial.get("email")
        if isinstance(email_cfg, dict):
            if "subject" in email_cfg:
                subject = _str(email_cfg["subject"], 300).replace("\n", " ").replace("\r", " ")
                new["email"]["subject"] = subject
            if "body" in email_cfg:
                new["email"]["body"] = ("" if email_cfg["body"] is None else str(email_cfg["body"]))[:20000]
            if "attachments" in email_cfg:
                names = email_cfg["attachments"]
                if not isinstance(names, list):
                    errors["email.attachments"] = "Attachments must be a list of file names."
                else:
                    available = {p.name for p in paths.uploads_dir().glob("*.pdf")}
                    kept, missing = [], []
                    for name in names:
                        name = _str(name, 255)
                        if name in available and name not in kept:
                            kept.append(name)
                        elif name:
                            missing.append(name)
                    new["email"]["attachments"] = kept
                    if missing:
                        errors["email.attachments"] = (
                            "These files are not uploaded (please upload them again): " + ", ".join(missing)
                        )

        targeting = partial.get("targeting")
        if isinstance(targeting, dict):
            if "city" in targeting:
                new["targeting"]["city"] = _str(targeting["city"], 80)
            if "country" in targeting:
                cc = _str(targeting["country"], 2).lower()
                new["targeting"]["country"] = cc if re.fullmatch(r"[a-z]{2}", cc) else ""
            if "segment" in targeting:
                seg = _str(targeting["segment"], 20).lower()
                if seg in ("any", "small", "mid"):
                    new["targeting"]["segment"] = seg
                else:
                    errors["targeting.segment"] = "Please choose small businesses, mid-sized businesses or all."
            for key, label in (("business_types", "business type"), ("areas", "area")):
                if key in targeting:
                    value = targeting[key]
                    if not isinstance(value, list):
                        errors[f"targeting.{key}"] = f"Please pick at least one {label} from the list."
                        continue
                    cleaned = []
                    for item in value:
                        item = _str(item, 80)
                        if item and item not in cleaned:
                            cleaned.append(item)
                    new["targeting"][key] = cleaned

        limits = partial.get("limits")
        if isinstance(limits, dict):
            lim = new["limits"]
            if "max_per_day" in limits:
                v = _as_int(limits["max_per_day"], "limits.max_per_day", errors, 1, HARD_MAX_PER_DAY,
                            f"Please type a whole number between 1 and {HARD_MAX_PER_DAY}.")
                if v is not None:
                    lim["max_per_day"] = v
            if "min_delay_s" in limits:
                v = _as_int(limits["min_delay_s"], "limits.min_delay_s", errors, 10, 3600,
                            "Please type a number of seconds (at least 10).")
                if v is not None:
                    lim["min_delay_s"] = v
            if "max_delay_s" in limits:
                v = _as_int(limits["max_delay_s"], "limits.max_delay_s", errors, 10, 7200,
                            "Please type a number of seconds (at least 10).")
                if v is not None:
                    lim["max_delay_s"] = v
            if "max_per_domain" in limits:
                v = _as_int(limits["max_per_domain"], "limits.max_per_domain", errors, 1, 20,
                            "Please type a whole number between 1 and 20.")
                if v is not None:
                    lim["max_per_domain"] = v
            if lim["max_delay_s"] < lim["min_delay_s"]:
                errors["limits.max_delay_s"] = "The longest pause must be at least as long as the shortest pause."
                lim["min_delay_s"] = current["limits"]["min_delay_s"]
                lim["max_delay_s"] = current["limits"]["max_delay_s"]

        new["limits"]["max_per_day"] = effective_daily_cap(new)
        save(new)
        return new, errors


def missing_for(settings: dict, mode: str) -> list[str]:
    """Plain-English list of what still has to be filled in before a run in ``mode``."""
    missing = []
    if mode in ("send", "both"):
        if not settings["profile"].get("full_name"):
            missing.append("your name (in 'About you')")
        if not settings["smtp"].get("email"):
            missing.append("your Gmail address (in 'Gmail connection')")
        if not settings["smtp"].get("app_password"):
            missing.append("your Gmail App Password (in 'Gmail connection')")
        if not settings["email"].get("subject", "").strip():
            missing.append("an email subject (in 'Your email')")
        if not settings["email"].get("body", "").strip():
            missing.append("the email text (in 'Your email')")
    if mode in ("scrape", "both"):
        if not settings["targeting"].get("city"):
            missing.append("the city or region to look in (in 'Who to target')")
        if not settings["targeting"].get("areas"):
            missing.append("at least one area (in 'Who to target')")
        if not settings["targeting"].get("business_types"):
            missing.append("at least one business type (in 'Who to target')")
    return missing
