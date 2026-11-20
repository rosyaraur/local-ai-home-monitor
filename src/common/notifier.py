import mimetypes
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage

ENV_PATH = os.path.expanduser("~/.alert_env")
QUIET_START_HOUR = 23  # 11:00 PM
QUIET_END_HOUR = 6     # 6:00 AM


def _load_env():
    cfg = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


def is_quiet_hours(now=None):
    hour = (now or datetime.now()).hour
    if QUIET_START_HOUR > QUIET_END_HOUR:
        # Overnight window (e.g., 23:00 -> 06:00)
        return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR
    return QUIET_START_HOUR <= hour < QUIET_END_HOUR


def send_alert(subject, body, image_path=None):
    cfg = _load_env()
    smtp_host = cfg.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(cfg.get("SMTP_PORT", "465"))
    smtp_user = cfg.get("SMTP_USER")
    smtp_pass = cfg.get("SMTP_PASS")
    alert_to = cfg.get("ALERT_TO", smtp_user)

    if not smtp_user or not smtp_pass:
        print("Alert skipped: SMTP_USER or SMTP_PASS missing in ~/.alert_env", flush=True)
        return False

    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = alert_to
    msg["Subject"] = subject
    msg.set_content(body)

    if image_path and os.path.exists(image_path):
        ctype, _ = mimetypes.guess_type(image_path)
        maintype, subtype = (ctype or "image/jpeg").split("/", 1)
        with open(image_path, "rb") as img:
            msg.add_attachment(
                img.read(),
                maintype=maintype,
                subtype=subtype,
                filename=os.path.basename(image_path),
            )

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"Email alert sent -> {alert_to} ({subject})", flush=True)
        return True
    except Exception as e:
        print(f"Email alert failed: {e}", flush=True)
        return False


if __name__ == "__main__":
    send_alert(
        subject="[Beelink] Test Alert",
        body=f"Communication module test at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.",
    )
