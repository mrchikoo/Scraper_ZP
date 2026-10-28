import io
import json

import pytest

from app import paths, server
from app.engine.leads import LeadStore
from app.engine.runner import Runner

from .conftest import auth_error

PW = "abcdefghijklmnop"


class FakeScraper:
    """Stands in for MapsScraper: 'finds' one lead per search."""

    def __init__(self, stop_event, log, store):
        self.stop_event, self.log, self.store = stop_event, log, store

    def scrape_search(self, url, on_lead):
        slug = url.split("/search/")[1].split("/")[0].split("?")[0].lower()
        slug = "".join(ch for ch in slug if ch.isalnum())[:20]
        on_lead(f"info@{slug}.in", f"Biz {slug}", f"https://{slug}.in/")
        return 1

    def close(self):
        pass


@pytest.fixture
def client(fake_smtp):
    runner = Runner(LeadStore(), smtp_factory=fake_smtp, scraper_factory=FakeScraper)
    app = server.create_app(runner=runner, smtp_factory=fake_smtp, shutdown=False)
    app.testing = True
    with app.test_client() as c:
        c.runner = runner
        yield c


def configure(client, **limits):
    payload = {
        "profile": {"full_name": "Alex", "business_name": "Acme Media", "phone": "+91 90000 00000"},
        "smtp": {"email": "alex@gmail.com", "app_password": PW},
        "email": {"subject": "Hi {{business_name}}", "body": "Hello {{business_name}}, I am {{my_name}}."},
        "targeting": {"city": "Mumbai", "country": "in", "business_types": ["cafes"], "areas": ["Bandra West", "Juhu"]},
        "limits": {"min_delay_s": 10, "max_delay_s": 10, **limits},
    }
    r = client.put("/api/settings", json=payload)
    assert r.get_json() == {"ok": True, "errors": {}}


def test_health(client):
    data = client.get("/api/health").get_json()
    assert data["ok"] is True and "version" in data and isinstance(data["chrome_found"], bool)
    assert data["data_dir"] == str(paths.data_dir())


def test_settings_roundtrip_never_returns_password(client):
    configure(client)
    r = client.get("/api/settings")
    raw = r.get_data(as_text=True)
    assert PW not in raw
    data = r.get_json()
    assert data["smtp"] == {"email": "alex@gmail.com", "has_app_password": True}
    assert data["targeting"]["areas"] == ["Bandra West", "Juhu"]
    # Partial update does not wipe other fields; attachments can't be set via PUT.
    r = client.put("/api/settings", json={"limits": {"max_per_day": 999}, "email": {"attachments": ["x.pdf"]}})
    assert r.get_json()["ok"] is True
    data = client.get("/api/settings").get_json()
    assert data["limits"]["max_per_day"] == 400
    assert data["email"]["attachments"] == []
    assert data["profile"]["full_name"] == "Alex"
    r = client.put("/api/settings", json={"smtp": {"email": "bad"}})
    assert r.get_json() == {"ok": False, "errors": {"smtp.email": r.get_json()["errors"]["smtp.email"]}}


def test_smtp_test_messages(client, fake_smtp):
    r = client.post("/api/smtp/test").get_json()
    assert r["ok"] is False and "App Password" in r["message"]
    configure(client)
    assert client.post("/api/smtp/test").get_json()["ok"] is True
    fake_smtp.login_error = auth_error(534, b"5.7.9 Application-specific password required")
    r = client.post("/api/smtp/test").get_json()
    assert r == {"ok": False, "message": r["message"]}
    assert "you need an App Password, not your normal one" in r["message"]
    assert PW not in r["message"]


def test_attachments(client):
    pdf = b"%PDF-1.4\n" + b"x" * 100
    r = client.post("/api/attachments", data={"file": (io.BytesIO(pdf), "My Portfolio.pdf")},
                    content_type="multipart/form-data")
    assert r.get_json() == {"ok": True, "name": "My_Portfolio.pdf"}
    assert client.get("/api/attachments").get_json() == [{"name": "My_Portfolio.pdf", "size": len(pdf)}]
    assert client.get("/api/settings").get_json()["email"]["attachments"] == ["My_Portfolio.pdf"]

    r = client.post("/api/attachments", data={"file": (io.BytesIO(b"hello"), "cv.docx")},
                    content_type="multipart/form-data").get_json()
    assert r["ok"] is False and "PDF" in r["message"]
    r = client.post("/api/attachments", data={"file": (io.BytesIO(b"not a pdf"), "fake.pdf")},
                    content_type="multipart/form-data").get_json()
    assert r["ok"] is False
    big = b"%PDF" + b"0" * (10 * 1024 * 1024 + 10)
    r = client.post("/api/attachments", data={"file": (io.BytesIO(big), "big.pdf")},
                    content_type="multipart/form-data").get_json()
    assert r["ok"] is False and "10 MB" in r["message"]

    assert client.delete("/api/attachments/My_Portfolio.pdf").get_json() == {"ok": True}
    assert client.get("/api/attachments").get_json() == []
    assert client.get("/api/settings").get_json()["email"]["attachments"] == []
    assert client.delete("/api/attachments/nope.pdf").get_json()["ok"] is False


def test_preview(client):
    configure(client)
    r = client.post("/api/email/preview", json={"subject": "For {{business_name}}", "body": "Hi {{my_name}}",
                                                "business_name": "Chai Point"}).get_json()
    assert r["subject"] == "For Chai Point"
    assert r["text"].startswith("Hi Alex") and "reply STOP" in r["text"]
    assert "<p>Hi Alex</p>" in r["html"]
    r = client.post("/api/email/preview", json={"subject": "", "body": ""}).get_json()
    assert set(r) == {"subject", "text", "html"}


def test_test_send(client, fake_smtp):
    configure(client)
    r = client.post("/api/email/test-send").get_json()
    assert r["ok"] is True and "alex@gmail.com" in r["message"]
    msg = fake_smtp.sent[-1]
    assert msg["To"] == "alex@gmail.com" and msg["Subject"].startswith("[Test]")


def test_areas_needs_a_city_first(client):
    data = client.get("/api/areas").get_json()
    assert data["city"] == "" and data["presets"] == []
    assert set(data["business_types"][0]) == {"key", "label"}


def test_areas_lists_places_for_the_typed_city(client, monkeypatch):
    fake = {"city": "Pune", "country": "in", "source": "online", "error": None,
            "presets": [{"name": "Koregaon Park", "lat": 18.5362, "lng": 73.8939}]}
    seen = []
    monkeypatch.setattr("app.engine.areas.localities", lambda city, http=None: (seen.append(city), fake)[1])
    data = client.get("/api/areas?city=Pune").get_json()
    assert seen == ["Pune"] and data["city"] == "Pune" and data["presets"][0]["name"] == "Koregaon Park"
    # the saved city is used when no city is passed
    client.put("/api/settings", json={"targeting": {"city": "Pune", "country": "in"}})
    client.get("/api/areas")
    assert seen == ["Pune", "Pune"]


def test_run_refuses_when_incomplete(client):
    r = client.post("/api/run/start", json={"mode": "send"}).get_json()
    assert r["ok"] is False and "Gmail" in r["message"]
    r = client.post("/api/run/start", json={"mode": "nonsense"}).get_json()
    assert r["ok"] is False


def test_full_run_scrape_and_send(client, fake_smtp, monkeypatch):
    monkeypatch.setattr("app.engine.runner.IDLE_POLL_S", 0.05)
    monkeypatch.setattr("app.engine.runner.random.uniform", lambda a, b: 0.01)
    configure(client)
    status = client.get("/api/run/status").get_json()
    assert status["state"] == "idle" and status["daily_cap"] == 100 and status["last_error"] is None

    r = client.post("/api/run/start", json={"mode": "both"}).get_json()
    assert r["ok"] is True
    assert client.post("/api/run/start", json={"mode": "both"}).get_json()["ok"] is False
    assert client.application.extensions["outreach_runner"].wait(timeout=10)

    status = client.get("/api/run/status").get_json()
    assert status["state"] == "idle"
    assert status["areas_total"] == 2 and status["areas_done"] == 2
    assert status["leads_found"] == 2 and status["sent_total"] == 2 and status["sent_today"] == 2

    leads = client.get("/api/leads").get_json()
    assert {l["status"] for l in leads} == {"sent"}
    assert all("sent_at" in l and l["business_name"].startswith("Biz") for l in leads)
    sent_to = sorted(m["To"] for m in fake_smtp.sent)
    assert sent_to == sorted(l["email"] for l in leads)
    body = fake_smtp.sent[0].get_body(("plain",)).get_content()
    assert "Hello Biz" in body and "reply STOP" in body

    logs = client.get("/api/run/logs?since=0").get_json()
    assert logs["next"] == len(logs["lines"]) and any("Sent to" in l for l in logs["lines"])
    later = client.get(f"/api/run/logs?since={logs['next']}").get_json()
    assert later == {"next": logs["next"], "lines": []}
    restarted = client.get("/api/run/logs?since=99999").get_json()  # client from an older session
    assert len(restarted["lines"]) == logs["next"]

    # A second run must never re-send to the same addresses.
    fake_smtp.sent.clear()
    assert client.post("/api/run/start", json={"mode": "send"}).get_json()["ok"] is True
    assert client.application.extensions["outreach_runner"].wait(timeout=10)
    assert fake_smtp.sent == []

    csv_resp = client.get("/api/leads/export.csv")
    assert csv_resp.mimetype == "text/csv"
    assert "attachment" in csv_resp.headers["Content-Disposition"]
    assert "email,business_name,website,area" in csv_resp.get_data(as_text=True)


def test_exclude_and_suppression(client, fake_smtp, monkeypatch):
    monkeypatch.setattr("app.engine.runner.random.uniform", lambda a, b: 0.01)
    configure(client)
    store = client.runner.store
    store.add_lead("info@sunrisecafe.in", "Sunrise Cafe", "https://sunrisecafe.in/", "Juhu")
    store.add_lead("owner@chaipoint.in", "Chai Point", "https://chaipoint.in/", "Juhu")
    assert client.post("/api/leads/exclude", json={"email": "INFO@sunrisecafe.in"}).get_json()["ok"] is True
    assert client.post("/api/leads/exclude", json={"email": "nonsense"}).get_json()["ok"] is False
    statuses = {l["email"]: l["status"] for l in client.get("/api/leads").get_json()}
    assert statuses == {"info@sunrisecafe.in": "excluded", "owner@chaipoint.in": "new"}
    assert "info@sunrisecafe.in" in paths.suppression_file().read_text()

    client.post("/api/run/start", json={"mode": "send"})
    assert client.runner.wait(timeout=10)
    assert [m["To"] for m in fake_smtp.sent] == ["owner@chaipoint.in"]


def test_auth_failure_stops_run_with_plain_message(client, fake_smtp):
    configure(client)
    client.runner.store.add_lead("info@sunrisecafe.in", "Sunrise Cafe")
    fake_smtp.login_error = auth_error()
    client.post("/api/run/start", json={"mode": "send"})
    assert client.runner.wait(timeout=10)
    status = client.get("/api/run/status").get_json()
    assert "App Password" in status["last_error"]
    assert client.get("/api/leads").get_json()[0]["status"] == "new"  # one failure: still retryable


def test_unknown_api_and_static(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.get_json()["ok"] is False
    r = client.get("/")
    assert r.status_code == 200 and b"<" in r.data


def test_password_never_in_log_file(client, fake_smtp, monkeypatch):
    import logging
    root = logging.getLogger()
    before = list(root.handlers)
    monkeypatch.setattr(server, "_logging_configured", False)
    server.setup_logging()
    added = [h for h in root.handlers if h not in before]
    configure(client)
    fake_smtp.login_error = auth_error()
    client.post("/api/smtp/test")
    logging.getLogger("outreach").info("leak test %s", PW)
    for h in logging.getLogger().handlers:
        h.flush()
    text = paths.app_log_file().read_text()
    for h in added:
        root.removeHandler(h)
        h.close()
    assert "leak test ********" in text
    assert PW not in text
