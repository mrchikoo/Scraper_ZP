from app.engine import areas, filters


def test_normalize_rejects_junk():
    n = filters.normalize_email_address
    assert n("  Info@SunriseCafe.in ") == "info@sunrisecafe.in"
    assert n("mailto:hello@cafe.co.in") == "hello@cafe.co.in"
    for bad in ["noreply@shop.in", "a@cafe.in", "logo@2x.png", "test123@cafe.in",
                "abc123def4567890ab@sentry.io", "user@example.com", "x y@cafe.in",
                "hello@cafe", "privacy@cafe.in", "postmaster@cafe.in", "café@cafe.in", ""]:
        assert n(bad) is None, bad


def test_is_sendable_india_rules():
    ok = ["info@sunrisecafe.in", "bookings@spicehub.co.in", "owner.salon@gmail.com",
          "hello@gymnation.com", "contact@yogaflow.io", "enquiry@realty.org",
          "cafeexpress@gmail.com", "frontdesk@clinic.net", "hi@rediffmail.com"]
    bad = ["hello@brandagency.in",        # agency domain (competitor)
           "team@zomato.com",             # platform
           "info@mumbaidigitalmarketing.com",
           "careers@cafe.in", "hr@cafe.in", "grievance@clinic.in", "press@hotel.com",
           "info@cafe.de",                # TLD not allowed
           "email@cafe.in",               # placeholder local part
           "john.doe@gmail.com",
           "info@www.cafe.in"]
    for e in ok:
        assert filters.is_sendable(e), e
    for e in bad:
        assert not filters.is_sendable(e), e


def test_extract_emails_variants():
    html = """
    <html><body>
      <a href="mailto:Owner@SunriseCafe.in?subject=Hi">Mail us</a>
      <p>Write to bookings [at] sunrisecafe [dot] in</p>
      <img src="hero@2x.png">
      <a href="/cdn-cgi/l/email-protection#{cf}">[email protected]</a>
      <span>noreply@sunrisecafe.in</span>
    </body></html>
    """
    # Cloudflare-encode "chef@sunrisecafe.in" with key 0x42.
    key = 0x42
    cf = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in "chef@sunrisecafe.in")
    found = filters.extract_emails(html.replace("{cf}", cf))
    assert found == {"owner@sunrisecafe.in", "bookings@sunrisecafe.in", "chef@sunrisecafe.in"}


def test_mumbai_builtin_list_is_the_offline_fallback():
    import requests

    class Offline:
        def get(self, *a, **k): raise requests.ConnectionError("no network")
        post = get

    res = areas.localities("Mumbai", http=Offline())
    assert res["source"] == "builtin" and res["country"] == "in"
    presets = res["presets"]
    names = {p["name"] for p in presets}
    assert len(presets) >= 40
    for must in ["Bandra West", "Andheri West", "Powai", "Colaba", "Lower Parel", "Juhu",
                 "Borivali West", "Thane West", "Vashi"]:
        assert must in names
    for p in presets:  # roughly inside the Mumbai metropolitan region
        assert 18.8 < p["lat"] < 19.4 and 72.7 < p["lng"] < 73.2, p
    keys = {b["key"] for b in areas.business_type_presets()}
    assert {"restaurants", "cafes", "salons", "gyms", "clinics", "boutiques", "real_estate", "coaching"} <= keys


def test_maps_url_is_english_and_country_biased_when_known():
    url = areas.maps_search_url("cafes", "Bandra West", "Mumbai", 19.0596, 72.8295, country="in")
    assert url.startswith("https://www.google.com/maps/search/cafes+in+Bandra+West%2C+Mumbai/@19.0596,72.8295,15z")
    assert url.endswith("?hl=en&gl=in")
    assert areas.maps_search_url("cafes", "Soho", "London").endswith("?hl=en")
    assert "@" not in areas.maps_search_url("cafes", "Somewhere New", "Mumbai").split("/search/")[1]


def test_website_key_and_relevant_pages():
    from app.engine import scraper
    assert scraper.website_key("https://www.SunriseCafe.in/menu") == "sunrisecafe.in"
    a = scraper.website_key("https://sites.google.com/view/gym-one/home")
    b = scraper.website_key("https://sites.google.com/view/gym-two")
    assert a != b
    html = """<a href="/contact-us">Contact</a><a href="/about">About us</a>
              <a href="https://other.com/contact">x</a><a href="mailto:x@y.in">m</a>
              <a href="/menu">Menu</a>"""
    pages = scraper.find_relevant_pages("https://sunrisecafe.in/", html)
    assert pages == ["https://sunrisecafe.in/contact-us", "https://sunrisecafe.in/about"]
    assert scraper.clean_website("https://www.google.com/url?q=https://cafe.in/&sa=x") == "https://cafe.in/"


def test_business_size_segments():
    from app.engine.scraper import brand_key, parse_review_count, segment_allows

    assert parse_review_count("Cafe Sunrise 4.5(1,234) Cafe") == 1234
    assert parse_review_count("Gym 4.2(1.2K)") == 1200
    assert parse_review_count("Gym 4.2(37)") == 37
    assert parse_review_count("New place, no rating") is None
    assert brand_key("Starbucks Coffee - Bandra") == brand_key("Starbucks Coffee, Andheri")

    assert segment_allows("small", 40) and segment_allows("small", None)
    assert not segment_allows("small", 900) and not segment_allows("small", 40, branches=3)
    assert segment_allows("mid", 900) and segment_allows("mid", 40, branches=3)
    assert not segment_allows("mid", 40) and not segment_allows("mid", None)
    assert segment_allows("any", None) and segment_allows("any", 5000, 9)
