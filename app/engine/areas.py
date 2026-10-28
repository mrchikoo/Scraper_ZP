"""Area lookup for any city (OpenStreetMap), business-type presets, and Google Maps URL building.

The user types a city or region first; ``localities(city)`` then returns the neighbourhoods inside it
so the frontend can show them as a checklist. Mumbai keeps a built-in list as an offline fallback.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from urllib.parse import quote_plus

import requests

from .. import paths

log = logging.getLogger("outreach.areas")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "LeadOutreach/1.0 (local desktop app; contact via project GitHub)"
HTTP_TIMEOUT = 25
MAX_LOCALITIES = 400
_PAGE = 40                 # Nominatim returns at most 40 rows per request
_MAX_PAGES = 3
_PAUSE_S = 1.1             # Nominatim asks for at most one request per second
# Searched in this order until a few areas turn up: big-city districts first, then smaller places.
_KIND_GROUPS = (("suburb",), ("neighbourhood", "quarter", "city_district", "borough"), ("town", "village", "hamlet"))

# (name, lat, lng): approximate centre of each locality.
MUMBAI_AREAS: list[tuple[str, float, float]] = [
    # South Mumbai
    ("Colaba", 18.9067, 72.8147),
    ("Fort", 18.9338, 72.8356),
    ("Churchgate", 18.9322, 72.8264),
    ("Marine Lines", 18.9447, 72.8235),
    ("Girgaon", 18.9550, 72.8150),
    ("Malabar Hill", 18.9548, 72.7985),
    ("Tardeo", 18.9690, 72.8120),
    ("Mumbai Central", 18.9690, 72.8205),
    ("Byculla", 18.9790, 72.8330),
    ("Worli", 19.0176, 72.8170),
    ("Lower Parel", 18.9980, 72.8300),
    ("Prabhadevi", 19.0166, 72.8295),
    # Central
    ("Dadar West", 19.0190, 72.8420),
    ("Dadar East", 19.0170, 72.8480),
    ("Matunga", 19.0270, 72.8550),
    ("Mahim", 19.0410, 72.8400),
    ("Sion", 19.0430, 72.8620),
    ("Wadala", 19.0210, 72.8650),
    ("Kurla", 19.0650, 72.8790),
    ("Chembur", 19.0620, 72.9000),
    ("Ghatkopar West", 19.0860, 72.9080),
    ("Ghatkopar East", 19.0790, 72.9100),
    ("Powai", 19.1176, 72.9060),
    ("Vikhroli", 19.1110, 72.9280),
    ("Bhandup", 19.1440, 72.9370),
    ("Mulund", 19.1720, 72.9560),
    # Western suburbs
    ("Bandra West", 19.0596, 72.8295),
    ("Bandra East", 19.0600, 72.8480),
    ("Bandra Kurla Complex", 19.0660, 72.8680),
    ("Khar West", 19.0700, 72.8360),
    ("Santacruz West", 19.0820, 72.8370),
    ("Santacruz East", 19.0800, 72.8560),
    ("Vile Parle West", 19.1000, 72.8400),
    ("Vile Parle East", 19.0990, 72.8530),
    ("Juhu", 19.1075, 72.8263),
    ("Andheri West", 19.1360, 72.8270),
    ("Andheri East", 19.1150, 72.8700),
    ("Versova", 19.1310, 72.8140),
    ("Lokhandwala", 19.1420, 72.8240),
    ("Jogeshwari", 19.1360, 72.8490),
    ("Goregaon West", 19.1630, 72.8410),
    ("Goregaon East", 19.1650, 72.8620),
    ("Malad West", 19.1870, 72.8410),
    ("Malad East", 19.1870, 72.8600),
    ("Kandivali West", 19.2050, 72.8410),
    ("Kandivali East", 19.2050, 72.8650),
    ("Borivali West", 19.2300, 72.8560),
    ("Borivali East", 19.2290, 72.8650),
    ("Dahisar", 19.2500, 72.8590),
    ("Mira Road", 19.2810, 72.8680),
    # Thane
    ("Thane West", 19.2183, 72.9781),
    ("Ghodbunder Road", 19.2600, 72.9700),
    # Navi Mumbai
    ("Vashi", 19.0771, 72.9986),
    ("Sanpada", 19.0640, 73.0090),
    ("Nerul", 19.0330, 73.0180),
    ("CBD Belapur", 19.0190, 73.0390),
    ("Kharghar", 19.0470, 73.0700),
    ("Airoli", 19.1590, 72.9990),
    ("Ghansoli", 19.1210, 73.0040),
    ("Kopar Khairane", 19.1030, 73.0110),
    ("Panvel", 18.9894, 73.1175),
    # Further out
    ("Dombivli", 19.2183, 73.0867),
    ("Kalyan", 19.2437, 73.1355),
]

# key, label shown in the UI, Google Maps search phrase.
BUSINESS_TYPES: list[dict[str, str]] = [
    {"key": "restaurants", "label": "Restaurants", "query": "restaurants"},
    {"key": "cafes", "label": "Cafes", "query": "cafes"},
    {"key": "bakeries", "label": "Bakeries & cake shops", "query": "bakeries"},
    {"key": "caterers", "label": "Caterers", "query": "caterers"},
    {"key": "salons", "label": "Hair & beauty salons", "query": "beauty salons"},
    {"key": "spas", "label": "Spas", "query": "spas"},
    {"key": "gyms", "label": "Gyms & fitness centres", "query": "gyms"},
    {"key": "yoga", "label": "Yoga studios", "query": "yoga studios"},
    {"key": "clinics", "label": "Clinics", "query": "clinics"},
    {"key": "dentists", "label": "Dental clinics", "query": "dental clinics"},
    {"key": "physiotherapists", "label": "Physiotherapists", "query": "physiotherapy clinics"},
    {"key": "opticians", "label": "Opticians", "query": "opticians"},
    {"key": "boutiques", "label": "Clothing boutiques", "query": "clothing boutiques"},
    {"key": "jewellers", "label": "Jewellers", "query": "jewellery shops"},
    {"key": "furniture", "label": "Furniture stores", "query": "furniture stores"},
    {"key": "real_estate", "label": "Real estate agents", "query": "real estate agents"},
    {"key": "interior_designers", "label": "Interior designers", "query": "interior designers"},
    {"key": "architects", "label": "Architects", "query": "architects"},
    {"key": "coaching", "label": "Coaching classes", "query": "coaching classes"},
    {"key": "preschools", "label": "Preschools & play schools", "query": "preschools"},
    {"key": "event_planners", "label": "Event & wedding planners", "query": "event planners"},
    {"key": "photographers", "label": "Photographers", "query": "photographers"},
    {"key": "travel_agents", "label": "Travel agents", "query": "travel agents"},
    {"key": "hotels", "label": "Hotels & guest houses", "query": "hotels"},
    {"key": "chartered_accountants", "label": "Chartered accountants", "query": "chartered accountants"},
    {"key": "lawyers", "label": "Lawyers & law firms", "query": "lawyers"},
    {"key": "car_services", "label": "Car service centres", "query": "car service centres"},
    {"key": "pet_shops", "label": "Pet shops & groomers", "query": "pet shops"},
    {"key": "florists", "label": "Florists", "query": "florists"},
]

_BUILTIN = {"mumbai": ("Mumbai", "in", MUMBAI_AREAS), "bombay": ("Mumbai", "in", MUMBAI_AREAS)}
_TYPE_INDEX = {bt["key"]: bt for bt in BUSINESS_TYPES}


def business_type_presets() -> list[dict]:
    return [{"key": bt["key"], "label": bt["label"]} for bt in BUSINESS_TYPES]


def _city_key(city: str) -> str:
    return re.sub(r"\s+", " ", (city or "").strip().lower())


def _preset(name: str, lat, lng) -> dict:
    return {"name": name, "lat": lat, "lng": lng}


# ---------------------------------------------------------------- city lookup (OpenStreetMap)
_cache_lock = threading.Lock()
_mem_cache: dict[str, dict] = {}


def _cache_file():
    return paths.data_dir() / "areas_cache.json"


def _load_disk_cache() -> dict:
    try:
        return json.loads(_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(key: str, entry: dict) -> None:
    with _cache_lock:
        _mem_cache[key] = entry
        data = _load_disk_cache()
        data[key] = entry
        try:
            paths.atomic_write_text(_cache_file(), json.dumps(data, ensure_ascii=False))
        except OSError as exc:  # a cache is optional
            log.warning("Could not save the area cache: %s", exc)


def _cached(key: str):
    with _cache_lock:
        hit = _mem_cache.get(key)
    if hit is None:
        hit = _load_disk_cache().get(key)
        if hit:
            with _cache_lock:
                _mem_cache[key] = hit
    return hit


def _geocode(city: str, http) -> dict | None:
    r = http.get(NOMINATIM_URL, params={"q": city, "format": "jsonv2", "limit": 1, "addressdetails": 1},
                 headers={"User-Agent": USER_AGENT, "Accept-Language": "en"}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    row = rows[0]
    south, north, west, east = (float(x) for x in row["boundingbox"])
    addr = row.get("address") or {}
    name = (row.get("name") or addr.get("city") or addr.get("town") or addr.get("state") or city).strip()
    return {"name": name, "country": (addr.get("country_code") or "").lower(),
            "bbox": [south, west, north, east], "lat": float(row["lat"]), "lng": float(row["lon"])}


def _search_places(bbox, kind: str, http) -> list[dict]:
    """Places of one OSM kind (e.g. ``suburb``) inside the bounding box, via Nominatim's "<kind> in <city>"."""
    south, west, north, east = bbox
    out: list[dict] = []
    seen_ids: list[str] = []
    for _ in range(_MAX_PAGES):
        params = {"q": kind.replace("_", " "), "format": "jsonv2", "limit": _PAGE, "bounded": 1,
                  "viewbox": f"{west},{north},{east},{south}"}
        if seen_ids:
            params["exclude_place_ids"] = ",".join(seen_ids)
        time.sleep(_PAUSE_S)
        r = http.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
                     timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        rows = r.json()
        for row in rows:
            seen_ids.append(str(row.get("place_id")))
            if row.get("category") == "place" and row.get("type") == kind:
                out.append(row)
        if len(rows) < _PAGE:
            break
    return out


def _nearby_localities(bbox, http) -> list[dict]:
    found: dict[str, dict] = {}
    for group in _KIND_GROUPS:
        for kind in group:
            for row in _search_places(bbox, kind, http):
                name = (row.get("name") or "").strip()
                if name and name.lower() not in found:
                    found[name.lower()] = _preset(name, round(float(row["lat"]), 4), round(float(row["lon"]), 4))
        if len(found) >= 3:
            break
    return sorted(found.values(), key=lambda a: a["name"].lower())[:MAX_LOCALITIES]


def localities(city: str, http=None) -> dict:
    """Areas inside ``city``. Never raises: problems come back as ``error`` for the screen to show.

    Returns ``{"city", "country", "presets": [{name, lat, lng}], "source", "error"}`` where ``source`` is
    ``online``, ``cache``, ``builtin`` or ``none``. ``offline`` is true when the lookup service could not be
    reached (the typed city is then kept so areas can be added by hand).
    """
    city = (city or "").strip()
    key = _city_key(city)
    empty = {"city": city, "country": "", "presets": [], "source": "none", "error": None}
    if not key:
        return empty
    hit = _cached(key)
    if hit:
        return {**hit, "source": "cache", "error": None}
    http = http or requests
    try:
        info = _geocode(city, http)
        if info is None:
            return {**empty, "error": f"I could not find a place called \"{city}\". Check the spelling, or add a country, for example \"Springfield, USA\"."}
        presets = _nearby_localities(info["bbox"], http)
        entry = {"city": info["name"], "country": info["country"], "presets": presets}
        if presets:
            _save_cache(key, entry)
        return {**entry, "source": "online", "error": None}
    except (requests.RequestException, ValueError, KeyError) as exc:
        log.warning("Area lookup for %r failed: %s", city, exc)
        built = _BUILTIN.get(key)
        if built:
            return {"city": built[0], "country": built[1], "presets": [_preset(*a) for a in built[2]],
                    "source": "builtin", "error": None}
        return {**empty, "offline": True,
                "error": "I could not look up areas right now (no internet connection, or the free map service is busy). "
                         "You can still type the areas you want by hand below."}


def find_area(name: str, city: str = ""):
    """Return (name, lat, lng) for a known area of ``city``, or (name, None, None) for a custom one."""
    name = (name or "").strip()
    key = _city_key(city)
    pool = None
    hit = _cached(key) if key else None
    if hit:
        pool = hit.get("presets") or []
    elif key in _BUILTIN:
        pool = [_preset(*a) for a in _BUILTIN[key][2]]
    for a in pool or []:
        if a["name"].lower() == name.lower():
            return (a["name"], a["lat"], a["lng"])
    return (name, None, None)


def business_type(key: str) -> dict:
    """Preset for a key; an unknown key is treated as a custom search phrase."""
    hit = _TYPE_INDEX.get(key)
    if hit:
        return hit
    phrase = (key or "").strip().replace("_", " ")
    return {"key": key, "label": phrase.capitalize(), "query": phrase}


def maps_search_url(query: str, area: str, city: str = "", lat=None, lng=None, zoom: int = 15,
                    country: str = "") -> str:
    """Google Maps search URL in English, biased to ``country`` (2-letter code) when known."""
    parts = [p for p in (area, city) if p]
    phrase = f"{query} in {', '.join(parts)}" if parts else query
    url = f"https://www.google.com/maps/search/{quote_plus(phrase)}"
    if lat is not None and lng is not None:
        url += f"/@{lat:.4f},{lng:.4f},{zoom}z"
    url += "?hl=en"
    if re.fullmatch(r"[a-z]{2}", country or ""):
        url += f"&gl={country}"
    return url
