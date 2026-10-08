"""Outgoing messages (email / SMS / WhatsApp) for fee reminders and parent alerts.

Every message is written to the `outbox` table, so the admin can see what was sent.  If a channel has
no credentials configured the message is stored with status 'logged' (a dry run) instead of failing -
so the whole flow can be tested before you buy an SMS plan.

Configuration (environment / .env):
  Email     SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
  SMS       SMS_PROVIDER=fast2sms  + FAST2SMS_API_KEY            (India, quick SMS route)
            SMS_PROVIDER=twilio    + TWILIO_SID, TWILIO_TOKEN, TWILIO_SMS_FROM
  WhatsApp  TWILIO_SID, TWILIO_TOKEN, TWILIO_WHATSAPP_FROM  (e.g. whatsapp:+14155238886)

Indian regulations: promotional/transactional SMS must use a DLT-registered sender ID and template, and
WhatsApp business-initiated messages must use an approved template.  The senders below post plain text;
register your templates with the provider and adjust the wording in features.py to match them.
"""
import base64
import json
import os
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage

import db

TIMEOUT = 15


def configured(channel):
    if channel == "email":
        return bool(os.getenv("SMTP_HOST"))
    if channel == "sms":
        p = os.getenv("SMS_PROVIDER", "").lower()
        if p == "fast2sms":
            return bool(os.getenv("FAST2SMS_API_KEY"))
        if p == "twilio":
            return all(os.getenv(k) for k in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_SMS_FROM"))
        return False
    if channel == "whatsapp":
        return all(os.getenv(k) for k in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_WHATSAPP_FROM"))
    return False


def status():
    return {c: configured(c) for c in ("email", "sms", "whatsapp")}


def _digits(phone):
    d = "".join(ch for ch in str(phone) if ch.isdigit())
    return d[-10:] if len(d) >= 10 else d


def e164(phone):
    d = _digits(phone)
    return "+91" + d if len(d) == 10 else "+" + "".join(ch for ch in str(phone) if ch.isdigit())


def _post(url, data=None, headers=None, json_body=None):
    h = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode()
        h["Content-Type"] = "application/json"
    elif isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (fixed https endpoints)
        return r.status, r.read().decode("utf-8", "replace")


def _twilio(to, body, whatsapp=False):
    sid, token = os.environ["TWILIO_SID"], os.environ["TWILIO_TOKEN"]
    frm = os.environ["TWILIO_WHATSAPP_FROM" if whatsapp else "TWILIO_SMS_FROM"]
    to = ("whatsapp:" if whatsapp else "") + e164(to)
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    _post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
          data={"To": to, "From": frm, "Body": body}, headers={"Authorization": "Basic " + auth})


def _send_raw(channel, to, subject, body):
    if channel == "email":
        msg = EmailMessage()
        msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER", "noreply@sincet.local")
        msg["To"] = to
        msg["Subject"] = subject or "SINCET notification"
        msg.set_content(body)
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=TIMEOUT) as s:
            s.starttls()
            if os.getenv("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
            s.send_message(msg)
    elif channel == "sms":
        if os.getenv("SMS_PROVIDER", "").lower() == "fast2sms":
            _post("https://www.fast2sms.com/dev/bulkV2", headers={"authorization": os.environ["FAST2SMS_API_KEY"]},
                  json_body={"route": "q", "message": body, "language": "english", "flash": 0,
                             "numbers": _digits(to)})
        else:
            _twilio(to, body)
    elif channel == "whatsapp":
        _twilio(to, body, whatsapp=True)
    else:
        raise ValueError("unknown channel")


def already_sent(channel, to, kind, ref):
    return bool(db.query_one(
        "SELECT id FROM outbox WHERE channel=%s AND recipient=%s AND kind=%s AND ref=%s "
        "AND status IN ('sent','logged') LIMIT 1", (channel, to, kind, ref)))


def send(channel, to, subject, body, kind, ref, now_str, dedupe=True):
    """Sends (or dry-run logs) one message. Returns 'sent' | 'logged' | 'failed' | 'duplicate'."""
    to = (to or "").strip()
    if not to:
        return "skipped"
    if dedupe and already_sent(channel, to, kind, ref):
        return "duplicate"
    status_, err = "logged", None
    if configured(channel):
        try:
            _send_raw(channel, to, subject, body)
            status_ = "sent"
        except Exception as exc:  # noqa: BLE001 - provider/network errors must not break the request
            status_, err = "failed", str(exc)[:240]
    db.insert("INSERT INTO outbox (channel, recipient, subject, body, kind, ref, status, error, created_at) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
              (channel, to[:120], (subject or "")[:150], body[:1000], kind, str(ref)[:40], status_, err, now_str))
    return status_
