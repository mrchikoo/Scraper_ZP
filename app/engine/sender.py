"""Email rendering and Gmail SMTP sending (port of the old email_sender.py).

* Placeholders: {{my_name}} {{my_business}} {{my_phone}} {{my_website}} {{business_name}}.
* A non-removable opt-out footer is always appended.
* One SMTP connection is kept open between sends, checked with NOOP and re-opened on demand;
  a send that fails on a connection problem is retried once after reconnecting.
* SMTP errors are translated into plain English for a non-technical user.
"""
from __future__ import annotations

import html as html_lib
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT = 30

OPT_OUT_FOOTER = "If you'd rather not hear from me, just reply STOP and I won't email you again."
FALLBACK_BUSINESS_NAME = "there"

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_]+)\s*\}\}")
_URL_RE = re.compile(r"(https?://[^\s<]+[^\s<.,;:!?)\]'\"])")


class SendError(Exception):
    """A send failed. ``message`` is plain English; ``fatal`` means stop sending entirely
    (bad password, daily limit), ``kind`` is a short machine-readable reason."""

    def __init__(self, message: str, fatal: bool = False, kind: str = "error"):
        super().__init__(message)
        self.message = message
        self.fatal = fatal
        self.kind = kind


# ------------------------------------------------------------------------- rendering
def placeholder_values(profile: dict, business_name: str | None) -> dict:
    profile = profile or {}
    name = (business_name or "").strip()
    return {
        "my_name": profile.get("full_name", "") or "",
        "my_business": profile.get("business_name", "") or "",
        "my_phone": profile.get("phone", "") or "",
        "my_website": profile.get("website", "") or "",
        "my_services": profile.get("services", "") or "",
        "business_name": name or FALLBACK_BUSINESS_NAME,
    }


def render_template(template: str, profile: dict, business_name: str | None = None) -> str:
    values = placeholder_values(profile, business_name)

    def repl(match):
        key = match.group(1).lower()
        return values[key] if key in values else match.group(0)

    text = _PLACEHOLDER_RE.sub(repl, template or "")
    # Tidy lines that became empty because a profile field was blank (e.g. no website).
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


def _text_to_html(text: str) -> str:
    paragraphs = re.split(r"\n\s*\n", text.strip()) if text.strip() else []
    parts = []
    for para in paragraphs:
        escaped = html_lib.escape(para)
        escaped = _URL_RE.sub(r'<a href="\1">\1</a>', escaped)
        parts.append("<p>" + escaped.replace("\n", "<br>\n") + "</p>")
    return "\n".join(parts)


def render_email(subject: str, body: str, profile: dict, business_name: str | None = None) -> dict:
    """Returns {subject, text, html}; both bodies end with the opt-out footer."""
    rendered_subject = render_template(subject, profile, business_name).replace("\n", " ").strip()
    rendered_body = render_template(body, profile, business_name)
    text = (rendered_body + "\n\n--\n" if rendered_body else "") + OPT_OUT_FOOTER
    html = (
        "<!DOCTYPE html>\n<html><body style=\"font-family:Arial,Helvetica,sans-serif;"
        "font-size:15px;line-height:1.5;color:#222\">\n"
        + _text_to_html(rendered_body)
        + "\n<p style=\"margin-top:28px;font-size:12px;color:#777\">"
        + html_lib.escape(OPT_OUT_FOOTER)
        + "</p>\n</body></html>"
    )
    return {"subject": rendered_subject, "text": text, "html": html}


def build_message(sender_email: str, sender_name: str, recipient: str, rendered: dict,
                  attachments: list[Path]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = rendered["subject"]
    msg["From"] = formataddr((sender_name, sender_email)) if sender_name else sender_email
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender_email.split("@")[-1] or None)
    msg["List-Unsubscribe"] = f"<mailto:{sender_email}?subject=STOP>"
    msg.set_content(rendered["text"])
    msg.add_alternative(rendered["html"], subtype="html")
    for path in attachments:
        path = Path(path)
        if not path.is_file():
            continue
        msg.add_attachment(path.read_bytes(), maintype="application", subtype="pdf", filename=path.name)
    return msg


# ------------------------------------------------------------------------- error text
def friendly_error(exc: BaseException) -> SendError:
    """Translate an exception from smtplib / the network into plain English."""
    if isinstance(exc, SendError):
        return exc
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        detail = (exc.smtp_error or b"").decode("utf-8", "ignore") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error or "")
        if exc.smtp_code == 534 or "application-specific password" in detail.lower():
            return SendError(
                "Gmail rejected the password: you need an App Password, not your normal one. "
                "Turn on 2-Step Verification in your Google account, create an App Password and paste it here.",
                fatal=True, kind="auth")
        return SendError(
            "Gmail did not accept this email address and App Password together. Check that the "
            "address is exactly the Gmail account that created the App Password, and copy the "
            "16-letter App Password again (old ones stop working if you change your Google password).",
            fatal=True, kind="auth")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return SendError("Gmail refused this recipient address, so it was skipped.", kind="recipient")
    if isinstance(exc, (smtplib.SMTPDataError, smtplib.SMTPSenderRefused)):
        detail = (exc.smtp_error or b"").decode("utf-8", "ignore") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error or "")
        low = detail.lower()
        if "5.4.5" in detail or "daily" in low or "limit exceeded" in low or "quota" in low:
            return SendError(
                "Gmail says you have reached its daily sending limit. Sending is paused; "
                "please try again tomorrow.", fatal=True, kind="quota")
        if "5.7.0" in detail or "suspicious" in low or "spam" in low:
            return SendError(
                "Gmail blocked this email as possible spam. Sending is paused. Try making your "
                "email more personal, lower the daily limit, and wait a few hours.",
                fatal=True, kind="blocked")
        return SendError("Gmail did not accept this email (" + (detail[:120] or "no reason given") + ").")
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return SendError("The connection to Gmail was interrupted.", kind="network")
    if isinstance(exc, smtplib.SMTPConnectError):
        return SendError("Could not connect to Gmail. Please try again in a few minutes.", kind="network")
    if isinstance(exc, (socket.gaierror,)):
        return SendError("Could not reach Gmail. Please check your internet connection.", kind="network")
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return SendError("Gmail took too long to answer. Please check your internet connection.", kind="network")
    if isinstance(exc, ssl.SSLError):
        return SendError("A secure connection to Gmail could not be made. Antivirus or office "
                         "network software may be blocking it.", kind="network")
    if isinstance(exc, OSError):
        return SendError("Could not reach Gmail. Please check your internet connection.", kind="network")
    if isinstance(exc, smtplib.SMTPException):
        return SendError("Gmail reported a problem: " + str(exc)[:150])
    return SendError("Something went wrong while sending: " + type(exc).__name__)


_NETWORK_ERRORS = (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError)


# ------------------------------------------------------------------------- SMTP client
class GmailSender:
    def __init__(self, email: str, app_password: str, smtp_factory=None):
        self.email = email
        self._password = app_password
        self._factory = smtp_factory or (
            lambda: smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=SMTP_TIMEOUT))
        self._server = None

    def __repr__(self):  # never show the password
        return f"GmailSender({self.email!r})"

    def connect(self):
        self.close()
        try:
            server = self._factory()
            server.login(self.email, self._password)
        except Exception as exc:
            raise friendly_error(exc) from None
        self._server = server
        return server

    def _ensure(self):
        if self._server is None:
            return self.connect()
        try:
            code, _ = self._server.noop()
            if code != 250:
                raise smtplib.SMTPServerDisconnected(f"NOOP {code}")
            return self._server
        except Exception:
            return self.connect()

    def send(self, msg: EmailMessage) -> None:
        """Send once; on a connection problem reconnect and retry once."""
        try:
            self._ensure().send_message(msg)
            return
        except SendError:
            raise
        except _NETWORK_ERRORS as exc:
            if isinstance(exc, smtplib.SMTPException) and not isinstance(
                    exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
                raise friendly_error(exc) from None
            first = exc
        except Exception as exc:
            raise friendly_error(exc) from None
        try:
            self.connect().send_message(msg)
        except SendError:
            raise
        except Exception as exc:
            raise friendly_error(exc if exc else first) from None

    def close(self):
        if self._server is not None:
            try:
                self._server.quit()
            except Exception:
                pass
        self._server = None


def test_login(email: str, app_password: str, smtp_factory=None) -> tuple[bool, str]:
    if not email or not app_password:
        return False, "Please enter your Gmail address and App Password first, then save."
    sender = GmailSender(email, app_password, smtp_factory)
    try:
        sender.connect()
        return True, f"Connected to Gmail as {email}. Everything is ready for sending."
    except SendError as err:
        return False, err.message
    finally:
        sender.close()
