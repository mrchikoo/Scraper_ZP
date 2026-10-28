"""Email extraction from web pages and filtering of junk / unsuitable addresses.

Two layers:
* :func:`normalize_email_address` drops malformed, placeholder and system addresses
  (noreply, postmaster, tracking IDs, file names that look like emails, ...).
* :func:`is_sendable` applies the outreach rules: allowed TLDs, no agencies / platforms /
  directories, no privacy / legal / HR inboxes. Freemail (gmail etc.) is allowed because many
  small Indian businesses use it.
"""
from __future__ import annotations

import fnmatch
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- layer 1

EMAIL_BLOCK_PATTERNS = {
    "dpo*@*",
    "*+noreply@*",
    "*+no-reply@*",
    "*@*.invalid",
    "*@*.local",
}

EMAIL_BLOCK_DOMAINS = {
    "email.com", "example.com", "example.net", "example.org", "example.in", "test.com",
    "invalid", "localhost", "localdomain", "mailinator.com", "yopmail.com", "tempmail.com",
    "10minutemail.com", "company.com", "doe.com", "domain.com", "sentry.io",
    "sentry.wixpress.com", "wixpress.com", "sentry-next.wixpress.com",
}

EMAIL_BLOCK_LOCALPARTS = {
    "noreply", "no-reply", "do-not-reply", "donotreply", "mailer-daemon", "postmaster",
    "hostmaster", "abuse", "spam", "unsubscribe", "privacy", "gdpr", "dpo", "billing",
    "invoice", "help", "helpdesk", "hotline", "test", "testing", "example", "sample", "demo",
    "fake", "dummy", "null", "none", "unknown", "webmaster", "name", "and", "api", "engineer",
    "implementation", "support", "security", "dataprotection", "user", "username",
    "youremail", "yourname", "your", "email", "mail", "abc", "xyz", "lorem",
}

EMAIL_BLOCK_LOCALPART_PREFIXES = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "bounce",
    "bounces", "dmarc", "dpo", "privacy", "gdpr",
}

EMAIL_BLOCK_LOCALPART_CONTAINS = {
    "no-reply", "noreply", "do-not-reply", "donotreply", "mailer-daemon", "bounce",
    "unsubscribe", "automated", "auto-reply", "autoresponder",
}

EMAIL_BLOCK_DOMAIN_SUFFIXES = {
    ".invalid", ".example", ".test", ".localhost", ".local",
    # Sentence fragments that the regex sometimes glues into a "domain".
    ".for", ".we", ".not", ".our", ".that", ".traditional", ".together",
}

# File extensions that sometimes look like an email domain (e.g. logo@2x.png).
EMAIL_BLOCK_DOMAIN_EXTENSIONS = {
    ".js", ".css", ".json", ".html", ".htm", ".xml", ".map", ".tar", ".gz", ".zip", ".rar",
    ".7z", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".pdf", ".mp4", ".woff",
    ".woff2", ".ttf", ".php", ".asp", ".aspx",
}


def normalize_email_address(value: str | None) -> str | None:
    """Return a lower-case, cleaned address, or None if it is junk."""
    if not value:
        return None
    value = str(value)
    if value.lower().startswith("mailto:"):
        value = value[7:]
    if value.lower().startswith("http://"):
        value = value[7:]
    cleaned = (
        value.strip()
        .replace(" ", "").replace(" ", "").replace("​", "").replace("﻿", "")
    )
    normalized = cleaned.lower().strip(".,;:<>()[]{}\"'")

    if any(ord(ch) > 127 for ch in normalized) or any(ch.isspace() for ch in normalized):
        return None
    if normalized.count("@") != 1:
        return None
    local_part, domain = normalized.split("@", 1)
    if not local_part or not domain:
        return None
    if "." not in domain or ".." in domain or domain.endswith(".") or domain.startswith("."):
        return None
    if ".." in local_part or local_part.startswith(".") or local_part.endswith("."):
        return None
    if len(local_part) == 1:
        return None
    if "/" in domain or "\\" in domain:
        return None
    if any(fnmatch.fnmatch(normalized, p) for p in EMAIL_BLOCK_PATTERNS):
        return None
    if domain in EMAIL_BLOCK_DOMAINS:
        return None
    if any(domain.endswith(s) for s in EMAIL_BLOCK_DOMAIN_SUFFIXES):
        return None
    if any(domain.endswith(ext) for ext in EMAIL_BLOCK_DOMAIN_EXTENSIONS):
        return None
    if local_part in EMAIL_BLOCK_LOCALPARTS:
        return None
    if any(local_part.startswith(p) for p in EMAIL_BLOCK_LOCALPART_PREFIXES):
        return None
    if any(t in local_part for t in EMAIL_BLOCK_LOCALPART_CONTAINS):
        return None
    if re.fullmatch(r"(?:test|fake|dummy|sample|example|demo)[._-]?\d*", local_part):
        return None
    if re.fullmatch(r"[0-9a-f]{16,}", local_part):  # Sentry / tracking IDs
        return None
    return normalized


# --------------------------------------------------------------------------- layer 2

FREEMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com",
    "rediffmail.com", "rediff.com", "hotmail.com", "hotmail.co.in", "outlook.com",
    "outlook.in", "live.com", "live.in", "msn.com", "icloud.com", "me.com", "aol.com",
    "zohomail.com", "zohomail.in", "proton.me", "protonmail.com", "indiatimes.com",
    "sify.com", "vsnl.net", "vsnl.com",
}

# Last label of the domain. ".co.in", ".org.in", ".net.in" etc. end in "in".
ALLOWED_TLDS = {
    "in", "com", "net", "org", "io", "co", "biz", "info", "me", "app", "ai", "tech",
    "shop", "store", "online", "site", "website", "studio", "salon", "spa", "fitness",
    "clinic", "health", "care", "dental", "doctor", "realty", "estate", "properties",
    "education", "academy", "school", "guru", "events", "photography", "travel", "cafe",
    "restaurant", "kitchen", "food", "bar", "club", "live", "world", "global", "life",
    "agency", "design", "fashion", "boutique", "jewelry", "beauty", "space",
    "page", "pro", "us", "uk", "ae", "coffee", "bakery", "pizza", "fit", "gym", "yoga",
    "hair", "dentist", "clothing", "furniture", "photo", "photos", "wedding", "law",
    "legal", "accountant", "cab", "car", "cars", "pet", "pets", "florist", "flowers",
    "hotel", "rest", "today", "one", "xyz",
}

PLACEHOLDER_DOMAINS = {
    "email.com", "mysite.com", "domain.com", "example.com", "yourdomain.com", "website.com",
    "company.com", "xyz.com", "yoursite.com", "aaa.com", "abc.com", "gmail.co", "gmial.com",
    "gamil.com", "mail.com", "yourcompany.com", "yourbusiness.com", "sitename.com",
}

PLACEHOLDER_LOCALS = {
    "email", "name", "lorem", "abc", "yourname", "youremail", "your.name", "firstname",
    "first.last", "john", "johndoe", "john.doe", "jane", "janedoe", "user", "username",
}

# Not the business itself: agencies (competitors), platforms, directories, hosters.
DOMAIN_KEYWORDS = (
    "marketing", "agency", "webdesign", "websolution", "webtech", "infotech", "digital",
    "seo", "media", "advert", "branding", "hosting", "software", "wix", "jimdo",
    "squarespace", "godaddy", "hostinger", "bigrock", "webflow", "wordpress", "shopify",
    "sentry", "google", "facebook", "instagram", "youtube", "linkedin", "twitter",
    "zomato", "swiggy", "dineout", "eazydiner", "magicpin", "justdial", "sulekha",
    "indiamart", "tradeindia", "practo", "lybrate", "urbancompany", "urbanclap",
    "housing.com", "99acres", "magicbricks", "nobroker", "makemytrip", "goibibo",
    "booking.com", "tripadvisor", "oyorooms", "airbnb", "amazon", "flipkart", "myntra",
    "nykaa", "freshworks", "razorpay", "paytm", "phonepe", "uber.com", "olacabs",
    "gov.in", "nic.in", "mcgm", "framer", "vimeo", "canva.com",
)

# Inboxes that will not read a sales pitch (or must not be pitched).
LOCAL_KEYWORDS = (
    "privacy", "abuse", "webmaster", "noreply", "no-reply", "press", "newsletter", "billing",
    "invoice", "accounts", "support", "grievance", "nodal", "compliance", "legal", "investor",
    "career", "jobs", "recruit", "hiring", "resume", "imprint", "dpo", "u003", "u00a",
)
LOCAL_EXACT_BLOCK = {"hr", "cv"}

EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")


def is_sendable(email: str) -> bool:
    """True if a normalized address is a reasonable outreach target."""
    if not email or not EMAIL_RE.match(email):
        return False
    local, domain = email.split("@", 1)
    if domain.rsplit(".", 1)[-1] not in ALLOWED_TLDS:
        return False
    if domain in PLACEHOLDER_DOMAINS or local in PLACEHOLDER_LOCALS or domain.startswith("www."):
        return False
    if domain not in FREEMAIL and any(k in domain for k in DOMAIN_KEYWORDS):
        return False
    if local in LOCAL_EXACT_BLOCK:
        return False
    # Match keywords at the start of each word of the local part, so "press" blocks
    # press@ / media.press@ but not cafeexpress@.
    tokens = [t for t in re.split(r"[._+-]", local) if t]
    if any(t.startswith(k) for t in tokens for k in LOCAL_KEYWORDS):
        return False
    return True


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def is_freemail(email_or_domain: str) -> bool:
    return email_domain(email_or_domain) in FREEMAIL


# --------------------------------------------------------------------------- extraction

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
OBFUSCATED_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+\s*(?:\(at\)|\[at\]|\{at\}|\sat\s)\s*[A-Za-z0-9-]+"
    r"(?:\s*(?:\.|\(dot\)|\[dot\]|\{dot\}|\sdot\s)\s*[A-Za-z0-9-]+)*"
    r"\s*(?:\.|\(dot\)|\[dot\]|\{dot\}|\sdot\s)\s*[A-Za-z]{2,}\b",
    re.IGNORECASE,
)


def _deobfuscate(candidate: str) -> str:
    value = candidate.strip().lower()
    for old, new in (("(at)", "@"), ("[at]", "@"), ("{at}", "@"), (" at ", "@"),
                     ("(dot)", "."), ("[dot]", "."), ("{dot}", "."), (" dot ", ".")):
        value = value.replace(old, new)
    return value.replace(" ", "")


def _decode_cfemail(encoded: str) -> str | None:
    """Decode Cloudflare's email protection (data-cfemail / #hex) encoding."""
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except (ValueError, IndexError):
        return None


def extract_emails(html: str, text: str = "") -> set[str]:
    """Find all plausible (normalized, layer-1 filtered) email addresses in a page."""
    html = html or ""
    raw: set[str] = set()
    raw.update(EMAIL_PATTERN.findall(html))
    if text:
        raw.update(EMAIL_PATTERN.findall(text))
    for source in (html, text):
        for token in OBFUSCATED_PATTERN.findall(source or ""):
            raw.add(_deobfuscate(token))

    try:
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if href.lower().startswith("mailto:"):
                mail = unquote(href.split(":", 1)[1].split("?", 1)[0]).strip()
                for part in mail.split(","):
                    if part.strip():
                        raw.add(part.strip())
            elif "/cdn-cgi/l/email-protection#" in href:
                decoded = _decode_cfemail(href.rsplit("#", 1)[-1])
                if decoded:
                    raw.add(decoded)
        for node in soup.select("[data-cfemail]"):
            decoded = _decode_cfemail(node.get("data-cfemail", ""))
            if decoded:
                raw.add(decoded)
        if not text:
            visible = soup.get_text(" ")
            raw.update(EMAIL_PATTERN.findall(visible))
    except Exception:  # pragma: no cover - parser errors on exotic markup
        pass

    return {n for item in raw if (n := normalize_email_address(item))}
