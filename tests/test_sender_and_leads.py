import smtplib

import pytest

from app import paths
from app.engine import sender
from app.engine.leads import LeadStore

from .conftest import auth_error

PROFILE = {"full_name": "Alex", "business_name": "Acme Media", "phone": "", "website": ""}


def _msg(to="info@cafe.in", attachments=()):
    rendered = sender.render_email("Hi {{business_name}}", "Hello", PROFILE, "Cafe")
    return sender.build_message("alex@gmail.com", "Alex", to, rendered, list(attachments))


def test_message_structure(tmp_path):
    pdf = tmp_path / "portfolio.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    msg = _msg(attachments=[pdf, tmp_path / "missing.pdf"])
    assert msg["From"] == "Alex <alex@gmail.com>"
    assert msg["List-Unsubscribe"] == "<mailto:alex@gmail.com?subject=STOP>"
    parts = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in parts and "text/html" in parts
    atts = list(msg.iter_attachments())
    assert len(atts) == 1 and atts[0].get_filename() == "portfolio.pdf"
    assert atts[0].get_content_type() == "application/pdf"


def test_send_reconnects_once_on_disconnect(fake_smtp):
    fake_smtp.send_errors = [smtplib.SMTPServerDisconnected("gone")]
    g = sender.GmailSender("alex@gmail.com", "abcdefghijklmnop", fake_smtp)
    g.send(_msg())
    assert len(fake_smtp.sent) == 1 and len(fake_smtp.instances) == 2


def test_send_errors_are_plain_english(fake_smtp):
    g = sender.GmailSender("alex@gmail.com", "abcdefghijklmnop", fake_smtp)
    fake_smtp.send_errors = [smtplib.SMTPDataError(550, b"5.4.5 Daily user sending limit exceeded.")]
    with pytest.raises(sender.SendError) as e:
        g.send(_msg())
    assert e.value.fatal and e.value.kind == "quota" and "daily sending limit" in e.value.message

    fake_smtp.send_errors = [smtplib.SMTPRecipientsRefused({"x@cafe.in": (550, b"no")})]
    with pytest.raises(sender.SendError) as e:
        g.send(_msg())
    assert not e.value.fatal

    ok, message = sender.test_login("alex@gmail.com", "abcdefghijklmnop",
                                    lambda: (_ for _ in ()).throw(OSError("no network")))
    assert not ok and "internet" in message
    fake_smtp.login_error = auth_error()
    ok, message = sender.test_login("alex@gmail.com", "abcdefghijklmnop", fake_smtp)
    assert not ok and "App Password" in message and "abcdefghijklmnop" not in message
    assert "abcdefghijklmnop" not in repr(g)


def test_sent_log_survives_restart_and_crash():
    store = LeadStore()
    for e in ("a1@cafe.in", "b2@cafe.in", "c3@cafe.in"):
        assert store.add_lead(e, "Biz")
    assert not store.add_lead("A1@cafe.in")  # dedupe, case-insensitive
    store.mark_attempt("a1@cafe.in")
    store.mark_sent("a1@cafe.in")
    store.mark_attempt("b2@cafe.in")  # app "crashes" here, mid-send
    store.mark_attempt("c3@cafe.in")
    store.mark_failed("c3@cafe.in", "refused")

    fresh = LeadStore()  # restart
    assert fresh.was_sent("a1@cafe.in") and fresh.was_sent("b2@cafe.in")
    assert not fresh.was_sent("c3@cafe.in")
    assert fresh.next_pending(5)["email"] == "c3@cafe.in"
    assert fresh.next_pending(2) is None  # cafe.in already had 2 emails
    assert fresh.sent_last_24h() == 2
    assert paths.leads_file().exists() and not list(paths.data_dir().glob(".*.tmp"))


def test_per_domain_cap_and_freemail():
    store = LeadStore()
    for e in ("a1@cafe.in", "b2@cafe.in", "c3@cafe.in", "x1@gmail.com", "x2@gmail.com"):
        store.add_lead(e)
    sent = []
    while (lead := store.next_pending(max_per_domain=2)) is not None:
        store.mark_sent(lead["email"])
        sent.append(lead["email"])
    assert sorted(sent) == ["a1@cafe.in", "b2@cafe.in", "x1@gmail.com", "x2@gmail.com"]


def test_domain_suppression():
    store = LeadStore()
    store.add_lead("a1@cafe.in")
    store.suppress("@cafe.in")
    assert store.next_pending(2) is None
    assert store.list_leads()[0]["status"] == "excluded"


def test_csv_formula_injection_is_neutralised():
    store = LeadStore()
    store.add_lead("a1@cafe.in", "=HYPERLINK(\"http://evil\")")
    assert "'=HYPERLINK" in store.export_csv()


def test_one_pitch_per_business_website():
    store = LeadStore()
    store.add_lead("owner@gmail.com", "Boojee", "https://boojee.in/")
    store.add_lead("hello@boojee.in", "Boojee", "https://boojee.in/")
    first = store.next_pending(2)
    store.mark_sent(first["email"])
    assert store.next_pending(2) is None
