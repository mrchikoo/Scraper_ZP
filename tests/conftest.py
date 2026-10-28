import smtplib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("OUTREACH_DATA_DIR", str(d))
    return d


class FakeSMTP:
    """Records what would have been sent. Class attributes control behaviour."""

    instances = []
    sent = []
    login_error = None
    send_errors = []  # exceptions raised by successive send_message calls

    def __init__(self, *a, **kw):
        self.logged_in = False
        self.closed = False
        FakeSMTP.instances.append(self)

    def login(self, user, password):
        if FakeSMTP.login_error is not None:
            raise FakeSMTP.login_error
        self.user, self.password = user, password
        self.logged_in = True

    def noop(self):
        return (250, b"OK")

    def send_message(self, msg):
        if FakeSMTP.send_errors:
            raise FakeSMTP.send_errors.pop(0)
        FakeSMTP.sent.append(msg)

    def quit(self):
        self.closed = True

    @classmethod
    def reset(cls):
        cls.instances, cls.sent, cls.login_error, cls.send_errors = [], [], None, []


@pytest.fixture
def fake_smtp():
    FakeSMTP.reset()
    yield FakeSMTP
    FakeSMTP.reset()


def auth_error(code=535, text=b"5.7.8 Username and Password not accepted"):
    return smtplib.SMTPAuthenticationError(code, text)
