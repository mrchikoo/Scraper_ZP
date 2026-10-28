"""Google Maps -> business websites -> email addresses (port of the old main.py).

Chrome runs headless with a dedicated profile in the data dir and is started through
Selenium Manager (Selenium >= 4.20 downloads the matching driver itself). The user's own
Chrome profile is never touched. Every wait checks the stop flag so a stop is quick.
"""
from __future__ import annotations

import os
import platform
import random
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

from .. import paths
from . import filters

MAX_RELEVANT_PAGES = 6
MAX_LISTINGS_PER_SEARCH = 120
SEARCH_TIMEOUT_S = 45 * 60
HTTP_TIMEOUT_S = 20

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36"
)

LISTING_XPATH = ".//a[contains(@class,'hfpxzc') and contains(@href,'/maps/place/')]"
TITLE_XPATH = "//h1[contains(@class,'DUwDvf')]"
WEBSITE_XPATHS = (
    "//a[contains(@data-item-id, 'authority') and @href]",
    "//a[contains(@aria-label, 'Website') and @href]",
)
CONSENT_XPATHS = (
    "//button[contains(., 'Accept all')]",
    "//button[@aria-label='Accept all']",
    "//button[contains(., 'I agree')]",
    "//button[contains(., 'Agree')]",
    "//input[@type='submit' and contains(@value, 'Accept all')]",
)
# Listed as "website" on Maps but they are not the business's own site.
SOCIAL_DOMAINS = (
    "instagram.com", "facebook.com", "fb.com", "wa.me", "whatsapp.com", "api.whatsapp.com",
    "twitter.com", "x.com", "youtube.com", "linkedin.com", "zomato.com", "swiggy.com",
    "justdial.com", "magicpin.in", "dineout.co.in", "practo.com", "sulekha.com",
    "business.site", "g.page", "goo.gl", "maps.app.goo.gl",
)
SPONSORED_RE = re.compile(r"\b(sponsored|promoted)\b", re.IGNORECASE)

# Link text / URL fragments of pages that usually show an email address.
PAGE_KEYWORDS = (
    "contact", "contact-us", "contactus", "reach-us", "reach us", "get-in-touch",
    "get in touch", "enquiry", "enquire", "inquiry", "about", "about-us", "who-we-are",
    "our-story", "team", "locate", "location", "visit-us", "book", "appointment",
)


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class StopRequested(Exception):
    pass


# --------------------------------------------------------------------------- Chrome
def find_chrome() -> str | None:
    """Path of an installed Chrome / Chromium, or None."""
    env = os.environ.get("OUTREACH_CHROME_BINARY") or os.environ.get("CHROME_PATH")
    if env and Path(env).is_file():
        return env
    system = platform.system()
    candidates: list[str] = []
    if system == "Windows":
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        try:
            import winreg  # type: ignore

            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                        candidates.append(winreg.QueryValue(key, None))
                except OSError:
                    pass
        except ImportError:
            pass
    elif system == "Darwin":
        candidates += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
        candidates += ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    return None


def _needs_no_sandbox() -> bool:
    if os.environ.get("OUTREACH_IN_DOCKER") == "1" or Path("/.dockerenv").exists():
        return True
    return hasattr(os, "geteuid") and platform.system() == "Linux" and os.geteuid() == 0


def make_driver(chrome_path: str | None = None):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    binary = chrome_path or find_chrome()
    if binary:
        options.binary_location = binary
    options.add_argument("--headless=new")
    options.add_argument(f"--user-data-dir={paths.chrome_profile_dir()}")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--lang=en-IN")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
    if _needs_no_sandbox():
        options.add_argument("--no-sandbox")
    options.add_experimental_option("prefs", {"intl.accept_languages": "en-IN,en"})
    options.page_load_strategy = "eager"
    driver_path = os.environ.get("OUTREACH_CHROMEDRIVER", "").strip()
    if driver_path:
        from selenium.webdriver.chrome.service import Service

        driver = webdriver.Chrome(service=Service(executable_path=driver_path), options=options)
    else:
        driver = webdriver.Chrome(options=options)  # Selenium Manager resolves chromedriver
    driver.set_page_load_timeout(40)
    return driver


# --------------------------------------------------------------------------- helpers
_user_agents: list[str] | None = None


def random_user_agent() -> str:
    global _user_agents
    if _user_agents is None:
        try:
            text = paths.resource_path("resources", "useragents.txt").read_text(encoding="utf-8")
            _user_agents = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        except OSError:
            _user_agents = []
    return random.choice(_user_agents) if _user_agents else DEFAULT_USER_AGENT


def is_google_redirect(url: str) -> bool:
    return any(x in url for x in ("google.com/aclk", "google.com/url", "google.co.in/url", "google.co.in/aclk"))


def resolve_redirect(url: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    for key in ("adurl", "q", "url"):
        value = (query.get(key) or [""])[0].strip()
        if value.startswith("http"):
            return value
    try:
        r = requests.get(url, headers={"User-Agent": random_user_agent()}, timeout=HTTP_TIMEOUT_S, allow_redirects=True)
        return r.url
    except requests.RequestException:
        return None


def site_domain(url: str) -> str:
    return urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")


# Hosts shared by many unrelated small-business sites: dedupe by host + path, not host.
SHARED_HOSTS = (
    "sites.google.com", "wixsite.com", "blogspot.com", "wordpress.com", "godaddysites.com",
    "weebly.com", "linktr.ee", "carrd.co", "webnode.com", "jimdosite.com", "site123.me",
)


def website_key(url: str) -> str:
    """What counts as 'the same website' for the already-checked list."""
    domain = site_domain(url)
    if any(domain == h or domain.endswith("." + h) for h in SHARED_HOSTS):
        segments = [p for p in urlparse(url).path.lower().split("/") if p][:2]
        return "/".join([domain] + segments)
    return domain


def clean_website(url: str | None) -> str | None:
    if not url:
        return None
    if is_google_redirect(url):
        url = resolve_redirect(url)
        if not url:
            return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"


def http_get(url: str) -> requests.Response | None:
    headers = {"User-Agent": random_user_agent(), "Accept-Language": "en-IN,en;q=0.9"}
    try:
        try:
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_S)
        except requests.exceptions.SSLError:
            # Many small-business sites have broken certificates; we only read public pages.
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_S, verify=False)
        if r.status_code >= 400 or "html" not in r.headers.get("Content-Type", "html"):
            return None
        return r
    except requests.RequestException:
        return None


def find_relevant_pages(base_url: str, html: str) -> list[str]:
    """Contact / about / enquiry pages on the same site, best first."""
    candidates: dict[str, int] = {}
    base_domain = site_domain(base_url)
    soup = BeautifulSoup(html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        href_raw = a["href"]
        href = href_raw.lower()
        text = a.get_text(" ", strip=True).lower()
        if not any(k in href or k in text for k in PAGE_KEYWORDS):
            continue
        abs_url = urljoin(base_url, href_raw)
        parsed = urlparse(abs_url)
        if parsed.scheme not in ("http", "https") or site_domain(abs_url) != base_domain:
            continue
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if clean.rstrip("/") == base_url.rstrip("/"):
            continue
        path = parsed.path.lower()
        score = 0
        if any(k in path or k in text for k in ("contact", "enquir", "inquir", "reach", "get-in-touch")):
            score += 100
        if any(k in path for k in ("about", "who-we-are", "our-story", "team")):
            score += 40
        if path.count("/") <= 2:
            score += 15
        candidates[clean] = max(score, candidates.get(clean, 0))
    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))
    return [u for u, _ in ranked[:MAX_RELEVANT_PAGES]]



# --------------------------------------------------------------------------- business size
SMALL_MAX_REVIEWS = 300  # independent shops stay under this; established / multi-branch ones go over
_REVIEWS_RE = re.compile(r"\(\s*([\d.,]+)\s*([kK]?)\s*\)")


def parse_review_count(text: str | None) -> int | None:
    """Review count from a Maps result card ("4.5(1,234)", "4.2(1.2K)"); None when not shown."""
    m = _REVIEWS_RE.search(text or "")
    if not m:
        return None
    raw, k = m.group(1), m.group(2)
    try:
        if k:
            return int(float(raw.replace(",", "")) * 1000)
        return int(raw.replace(",", "").replace(".", ""))
    except ValueError:
        return None


def brand_key(name: str | None) -> str:
    """'Starbucks Coffee - Bandra' and 'Starbucks Coffee, Andheri' share one key (same brand)."""
    return re.split(r"\s[-\u2013|,(]\s?|,", (name or "").lower().strip(), maxsplit=1)[0].strip()


def segment_allows(segment: str, reviews: int | None, branches: int = 1) -> bool:
    """'small' = independent small business, 'mid' = established or multi-branch, 'any' = everything.
    A card without a review count is treated as small (new or little-known businesses)."""
    if segment == "small":
        return branches < 2 and (reviews is None or reviews < SMALL_MAX_REVIEWS)
    if segment == "mid":
        return branches >= 2 or (reviews is not None and reviews >= SMALL_MAX_REVIEWS)
    return True

# --------------------------------------------------------------------------- scraper
class MapsScraper:
    """Scrapes one Maps search at a time. ``on_lead(email, business_name, website)`` is called
    for every new address, ``log(msg)`` for plain-English progress lines."""

    def __init__(self, stop_event: threading.Event, log: Callable[[str], None], store,
                 driver_factory=make_driver):
        self.stop_event = stop_event
        self.log = log
        self.store = store
        self._driver_factory = driver_factory
        self.driver = None
        self.segment = "any"  # 'any' | 'small' | 'mid', set by the runner

    # ---------------------------------------------------------------- lifecycle
    def start(self):
        if self.driver is None:
            self.driver = self._driver_factory()
        return self.driver

    def close(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.driver = None

    def _check_stop(self):
        if self.stop_event.is_set():
            raise StopRequested()

    def _sleep(self, lo: float, hi: float):
        if self.stop_event.wait(random.uniform(lo, hi)):
            raise StopRequested()

    # ---------------------------------------------------------------- page helpers
    def accept_consent(self, timeout: float = 4) -> bool:
        from selenium.webdriver.common.by import By

        driver = self.driver
        deadline = time.time() + timeout
        while time.time() < deadline:
            for xpath in CONSENT_XPATHS:
                try:
                    for button in driver.find_elements(By.XPATH, xpath):
                        if button.is_displayed():
                            button.click()
                            time.sleep(1.5)
                            return True
                except Exception:
                    continue
            if "consent." not in driver.current_url:
                return False
            time.sleep(0.5)
        return False

    def _feed(self):
        from selenium.webdriver.common.by import By

        feeds = self.driver.find_elements(By.XPATH, "//div[@role='feed']")
        best, best_count = None, -1
        for feed in feeds:
            try:
                count = len(feed.find_elements(By.XPATH, LISTING_XPATH))
            except Exception:
                continue
            if count > best_count:
                best, best_count = feed, count
        return best

    def _scroll_target(self, feed):
        return self.driver.execute_script(
            """
            let el = arguments[0];
            while (el) {
                const s = window.getComputedStyle(el);
                if ((el.scrollHeight - el.clientHeight) > 20 &&
                    ['auto', 'scroll', 'overlay'].includes(s.overflowY)) return el;
                el = el.parentElement;
            }
            return arguments[0];
            """,
            feed,
        )

    def _load_more(self, previous_count: int) -> tuple[bool, bool]:
        """Scroll the result list. Returns (grew, end_of_list)."""
        from selenium.webdriver.common.by import By

        for _ in range(4):
            self._check_stop()
            feed = self._feed()
            if feed is None:
                return False, True
            target = self._scroll_target(feed)
            self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", target)
            deadline = time.time() + random.uniform(6, 9)
            while time.time() < deadline:
                self._sleep(0.8, 1.4)
                try:
                    feed = self._feed()
                    count = len(feed.find_elements(By.XPATH, LISTING_XPATH)) if feed is not None else 0
                    if count > previous_count:
                        return True, False
                    text = (feed.text if feed is not None else "").lower()
                    if "end of the list" in text:
                        return False, True
                except Exception:
                    pass
            try:  # nudge lazy loading: up a bit, then down again
                self.driver.execute_script("arguments[0].scrollTop = Math.max(arguments[0].scrollTop - 1200, 0);", target)
            except Exception:
                pass
        return False, False

    @staticmethod
    def _card_text(listing) -> str:
        from selenium.webdriver.common.by import By

        try:
            card = listing.find_element(By.XPATH, "./ancestor::div[@role='article'][1]")
        except Exception:
            card = listing.find_element(By.XPATH, "..")
        return card.text or ""

    @staticmethod
    def _is_sponsored(listing) -> bool:
        from selenium.webdriver.common.by import By

        try:
            parts = [listing.get_attribute("aria-label") or ""]
            try:
                card = listing.find_element(By.XPATH, "./ancestor::div[@role='article'][1]")
            except Exception:
                card = listing.find_element(By.XPATH, "..")
            parts.append(card.text or "")
            return bool(SPONSORED_RE.search(" ".join(parts)))
        except Exception:
            return False

    def _details_from_panel(self) -> tuple[str | None, str | None]:
        from selenium.webdriver.common.by import By

        name = website = None
        try:
            name = self.driver.find_element(By.XPATH, TITLE_XPATH).text.strip() or None
        except Exception:
            pass
        for xpath in WEBSITE_XPATHS:
            try:
                elems = self.driver.find_elements(By.XPATH, xpath)
                if elems:
                    website = elems[0].get_attribute("href")
                    break
            except Exception:
                continue
        return name, website

    def _details_in_new_tab(self, url: str) -> tuple[str | None, str | None]:
        """Fallback: open the listing in a separate tab of the same browser."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        driver = self.driver
        main = driver.current_window_handle
        try:
            driver.switch_to.new_window("tab")
            driver.get(url)
            self.accept_consent(timeout=2)
            try:
                WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.XPATH, TITLE_XPATH)))
            except Exception:
                pass
            return self._details_from_panel()
        except Exception:
            return None, None
        finally:
            try:
                if driver.current_window_handle != main:
                    driver.close()
                driver.switch_to.window(main)
            except Exception:
                pass

    def _open_listing(self, listing, href: str) -> tuple[str | None, str | None]:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        driver = self.driver
        token_match = re.search(r"!1s([^!]+)", unquote(href or ""))
        token = token_match.group(1) if token_match else None
        try:
            previous = driver.find_element(By.XPATH, TITLE_XPATH).text.strip()
        except Exception:
            previous = None
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", listing)
            driver.execute_script("arguments[0].click();", listing)

            def changed(d):
                try:
                    if token and token in unquote(d.current_url):
                        return True
                    title = d.find_element(By.XPATH, TITLE_XPATH).text.strip()
                    return bool(title) and title != previous
                except Exception:
                    return False

            WebDriverWait(driver, 8).until(changed)
            self._sleep(1.2, 2.5)
            return self._details_from_panel()
        except StopRequested:
            raise
        except Exception:
            return self._details_in_new_tab(href)

    # ---------------------------------------------------------------- websites
    def emails_from_website(self, website: str) -> set[str]:
        """Homepage first, then contact/about pages until one yields addresses."""
        found: set[str] = set()
        resp = http_get(website)
        html = resp.text if resp is not None else ""
        if html:
            found |= filters.extract_emails(html)
        if not found:
            rendered = self._rendered_html(website) if (not html or len(html) < 5000) else ""
            if rendered:
                html = html or rendered
                found |= filters.extract_emails(rendered)
        if found:
            return found
        for url in find_relevant_pages(website, html):
            self._check_stop()
            page = http_get(url)
            if page is not None:
                found |= filters.extract_emails(page.text)
            if found:
                break
        return found

    def _rendered_html(self, url: str) -> str:
        """Render a JavaScript-heavy site in a temporary tab of the same browser."""
        driver = self.driver
        if driver is None:
            return ""
        main = driver.current_window_handle
        try:
            driver.switch_to.new_window("tab")
            driver.get(url)
            time.sleep(2)
            return driver.page_source or ""
        except Exception:
            return ""
        finally:
            try:
                if driver.current_window_handle != main:
                    driver.close()
                driver.switch_to.window(main)
            except Exception:
                pass

    # ---------------------------------------------------------------- main loop
    def scrape_search(self, url: str, on_lead: Callable[[str, str, str], bool]) -> int:
        """Process one Maps search URL. Returns the number of businesses looked at."""
        from selenium.webdriver.common.by import By

        self._check_stop()
        driver = self.start()
        driver.get(url)
        self._sleep(2, 3.5)
        self.accept_consent(timeout=5)
        if "consent." in driver.current_url:
            driver.get(url)
            self._sleep(2, 3)

        started = time.time()
        processed: set[str] = set()
        looked_at = 0
        skipped_size = 0
        stagnation = 0

        while True:
            self._check_stop()
            if time.time() - started > SEARCH_TIMEOUT_S or len(processed) >= MAX_LISTINGS_PER_SEARCH:
                self.log("This search has been going for a while; moving on to the next one.")
                break
            feed = self._feed()
            if feed is None:
                # A search with exactly one result opens the business directly.
                name, website = self._details_from_panel()
                if name and not processed:
                    looked_at += 1
                    self._handle_business(name, website, on_lead)
                else:
                    self.log("Google Maps showed no list of results for this search.")
                break
            try:
                listings = feed.find_elements(By.XPATH, LISTING_XPATH)
            except Exception:
                self._sleep(1, 2)  # the list re-rendered while reading it; try again
                continue

            branches: dict[str, int] = {}
            if self.segment != "any":
                for listing in listings:
                    try:
                        key = brand_key(listing.get_attribute("aria-label"))
                    except Exception:
                        continue
                    if key:
                        branches[key] = branches.get(key, 0) + 1

            new = []
            for listing in listings:
                try:
                    href = listing.get_attribute("href")
                except Exception:
                    continue
                if href and href not in processed:
                    if self._is_sponsored(listing):
                        processed.add(href)
                        continue
                    if self.segment != "any":
                        try:
                            card = self._card_text(listing)
                            key = brand_key(listing.get_attribute("aria-label"))
                        except Exception:
                            card, key = "", ""
                        if not segment_allows(self.segment, parse_review_count(card), branches.get(key, 1)):
                            processed.add(href)
                            skipped_size += 1
                            continue
                    new.append((listing, href))

            for listing, href in new:
                self._check_stop()
                processed.add(href)
                looked_at += 1
                fallback_name = None
                try:
                    fallback_name = listing.get_attribute("aria-label")
                except Exception:
                    pass
                name, website = self._open_listing(listing, href)
                self._handle_business(name or fallback_name, website, on_lead)
                self._sleep(1, 2.5)

            grew, end = self._load_more(len(listings))
            if end:
                break
            stagnation = 0 if grew else stagnation + 1
            if stagnation >= 3:
                break
        if skipped_size:
            self.log(f"Skipped {skipped_size} businesses that do not match the chosen business size.")
        return looked_at

    def _handle_business(self, name, website, on_lead):
        name = (name or "").strip()
        label = name or "A business"
        site = clean_website(website)
        if not site:
            self.log(f"{label}: no website listed, skipped.")
            return
        domain = site_domain(site)
        if any(domain == d or domain.endswith("." + d) for d in SOCIAL_DOMAINS):
            self.log(f"{label}: only has a social media / listing page ({domain}), skipped.")
            return
        key = website_key(site)
        if self.store.website_seen(key):
            self.log(f"{label}: website already checked before, skipped.")
            return
        self.store.mark_website(key)
        try:
            emails = self.emails_from_website(site)
        except StopRequested:
            raise
        except Exception:
            emails = set()
        usable = sorted(e for e in emails if filters.is_sendable(e))
        if not usable:
            self.log(f"{label}: no usable email found on {domain}.")
            return
        added = [e for e in usable if on_lead(e, name, site)]
        if added:
            self.log(f"{label}: found {', '.join(added)}")
        else:
            self.log(f"{label}: email already in your list.")
