"""Send an email through Gmail (used by alerts.py)."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send(subject, html, text):
    missing = [k for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "EMAIL_TO") if not os.environ.get(k, "").strip()]
    if missing:
        raise SystemExit(f"::error::Missing secret(s): {', '.join(missing)}")
    user = os.environ["GMAIL_USER"].strip()
    pw = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
    to = os.environ["EMAIL_TO"].strip()
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
    except smtplib.SMTPAuthenticationError:
        raise SystemExit("::error::Gmail rejected the login. Check GMAIL_USER and GMAIL_APP_PASSWORD.")
