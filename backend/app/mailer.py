"""SMTP-based email delivery for SkillBridge.

Sends account-verification and password-reset emails. Configure via environment
variables (see below); if SMTP is not configured, the app falls back to writing
the link to the server log so the flow stays demoable in local/dev environments.

Env:
    SMTP_HOST        e.g. smtp.gmail.com
    SMTP_PORT        default 587 (STARTTLS)
    SMTP_USER        username (often the from-address)
    SMTP_PASS        app password / token
    SMTP_FROM        sender address (defaults to SMTP_USER)
    SKILLBRIDGE_APP_URL   public base URL for links (default http://localhost:8000)
    SKILLBRIDGE_EMAIL_DISABLED  set to "1" to force demo/log mode even if SMTP is set
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger("skillbridge.mailer")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
APP_URL = os.environ.get("SKILLBRIDGE_APP_URL", "http://localhost:8000").rstrip("/")
EMAIL_DISABLED = os.environ.get("SKILLBRIDGE_EMAIL_DISABLED", "0") == "1"


def email_configured():
    return bool(SMTP_HOST and SMTP_USER) and not EMAIL_DISABLED


def _send(to_email, subject, html_body, text_body):
    if not email_configured():
        log.info("SkillBridge email disabled/not configured — would send to %s: %s",
                 to_email, subject)
        return False
    from_addr = SMTP_FROM or SMTP_USER
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            if SMTP_PORT == 587:
                server.starttls()
                server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(from_addr, [to_email], msg.as_string())
        log.info("Sent email to %s: %s", to_email, subject)
        return True
    except Exception as exc:  # pragma: no cover - depends on external SMTP
        log.warning("Failed to send email to %s: %s", to_email, exc)
        return False


def verification_link(token):
    return f"{APP_URL}/verify?token={token}"


def send_verification_email(user, token):
    link = verification_link(token)
    name = user.get("display_name") or "there"
    subject = "Verify your SkillBridge account"
    text = f"Hi {name},\n\nVerify your SkillBridge account by opening:\n{link}\n\nIf you didn't create this account, ignore this email."
    html = (
        "<p>Hi <strong>" + name + "</strong>,</p>"
        "<p>Please verify your SkillBridge account by clicking the button below.</p>"
        '<p style="margin:24px 0"><a href="' + link + '" style="background:#0b7c79;color:#fff;'
        'padding:12px 22px;border-radius:6px;text-decoration:none">Verify my account</a></p>'
        "<p>Or open this link: <a href='" + link + "'>" + link + "</a></p>"
        "<p>If you didn't create this account, you can safely ignore this email.</p>"
    )
    return _send(user["email"], subject, html, text)


def send_reset_email(user, reset_token):
    link = f"{APP_URL}/reset?token={reset_token}"
    name = user.get("display_name") or "there"
    subject = "Reset your SkillBridge password"
    text = f"Hi {name},\n\nReset your SkillBridge password by opening:\n{link}\n\nIf you didn't request this, ignore this email."
    html = (
        "<p>Hi <strong>" + name + "</strong>,</p>"
        "<p>Reset your SkillBridge password:</p>"
        '<p style="margin:24px 0"><a href="' + link + '" style="background:#0b7c79;color:#fff;'
        'padding:12px 22px;border-radius:6px;text-decoration:none">Reset password</a></p>'
        "<p>Or open this link: <a href='" + link + "'>" + link + "</a></p>"
        "<p>If you didn't request this, you can ignore this email.</p>"
    )
    return _send(user["email"], subject, html, text)
