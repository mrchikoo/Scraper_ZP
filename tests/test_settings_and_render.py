import json

from app import paths, settings
from app.engine import sender


def test_defaults_and_masking(data_dir):
    cfg = settings.load()
    assert cfg["limits"]["max_per_day"] == 100
    assert cfg["targeting"]["city"] == "" and cfg["targeting"]["areas"] == []
    cfg, errors = settings.update({"smtp": {"email": "alex@gmail.com", "app_password": "abcd efgh ijkl mnop"}})
    assert errors == {}
    assert cfg["smtp"]["app_password"] == "abcdefghijklmnop"
    view = settings.public_view(settings.load())
    assert "app_password" not in view["smtp"]
    assert view["smtp"] == {"email": "alex@gmail.com", "has_app_password": True}
    assert "abcdefghijklmnop" not in json.dumps(view)


def test_empty_password_keeps_stored_one():
    settings.update({"smtp": {"email": "z@gmail.com", "app_password": "abcdefghijklmnop"}})
    cfg, errors = settings.update({"smtp": {"email": "z@gmail.com", "app_password": ""}})
    assert not errors and cfg["smtp"]["app_password"] == "abcdefghijklmnop"
    cfg, _ = settings.update({"smtp": {"email": "z@gmail.com"}})
    assert cfg["smtp"]["app_password"] == "abcdefghijklmnop"


def test_validation_errors_and_caps():
    cfg, errors = settings.update({
        "smtp": {"email": "not-an-email", "app_password": "short"},
        "limits": {"max_per_day": 5000, "min_delay_s": 60, "max_delay_s": 90, "max_per_domain": 3},
        "profile": {"full_name": "Alex"},
    })
    assert set(errors) == {"smtp.email", "smtp.app_password"}
    assert cfg["limits"]["max_per_day"] == 400  # hard ceiling
    assert cfg["profile"]["full_name"] == "Alex"  # valid parts still saved
    assert settings.load()["limits"]["min_delay_s"] == 60

    cfg, errors = settings.update({"limits": {"max_per_day": ""}})
    assert not errors and cfg["limits"]["max_per_day"] == 400  # empty box keeps value
    cfg, errors = settings.update({"limits": {"max_per_day": "abc"}})
    assert "limits.max_per_day" in errors
    cfg, errors = settings.update({"limits": {"min_delay_s": 200, "max_delay_s": 100}})
    assert "limits.max_delay_s" in errors and cfg["limits"]["min_delay_s"] == 60


def test_hand_edited_file_is_capped(data_dir):
    paths.settings_file().write_text(json.dumps({"limits": {"max_per_day": 9999}}))
    assert settings.load()["limits"]["max_per_day"] == 400


def test_missing_for():
    cfg = settings.load()
    assert any("App Password" in m for m in settings.missing_for(cfg, "send"))
    scrape = settings.missing_for(cfg, "scrape")
    assert any("city" in m for m in scrape) and any("area" in m for m in scrape)
    cfg, _ = settings.update({"targeting": {"city": "Pune", "areas": ["Baner"]}})
    assert settings.missing_for(cfg, "scrape") == []


PROFILE = {"full_name": "Alex", "business_name": "Acme Media", "phone": "+91 90000 00000", "website": ""}


def test_render_placeholders_and_footer():
    out = sender.render_email("Hi {{business_name}}", "Hello {{ business_name }},\n\n{{my_name}} from {{my_business}}\n{{my_website}}\n{{unknown}}",
                              PROFILE, "Sunrise <Cafe>")
    assert out["subject"] == "Hi Sunrise <Cafe>"
    assert "Hello Sunrise <Cafe>," in out["text"]
    assert "Alex from Acme Media" in out["text"]
    assert "{{unknown}}" in out["text"]
    assert out["text"].rstrip().endswith(sender.OPT_OUT_FOOTER)
    assert "Sunrise &lt;Cafe&gt;" in out["html"] and "<Cafe>" not in out["html"]
    assert "reply STOP" in out["html"]


def test_render_fallback_name_and_empty():
    out = sender.render_email("", "", PROFILE, None)
    assert out["subject"] == ""
    assert out["text"] == sender.OPT_OUT_FOOTER
    assert sender.render_template("Hi {{business_name}}", PROFILE, "") == "Hi there"


def test_segment_setting_validation():
    cfg, errors = settings.update({"targeting": {"segment": "mid", "business_types": ["wedding photographers"]}})
    assert not errors and cfg["targeting"]["segment"] == "mid"
    assert cfg["targeting"]["business_types"] == ["wedding photographers"]
    cfg, errors = settings.update({"targeting": {"segment": "huge"}})
    assert "targeting.segment" in errors and cfg["targeting"]["segment"] == "mid"
