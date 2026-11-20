# Local AI Home Monitor

A self-hosted, zero-cloud-cost home automation, surveillance, and alerting hub built for an Ubuntu mini-PC (tested on a Beelink MINI S13). It combines V4L2 webcam motion detection, a Dockerized YOLO object-detection watchdog, a centralized SSL email alerting module, automated stock market monitoring, and a Streamlit Command Center dashboard.

## Features

* **Motion Detection with Burst Capture (`src/vision/motion_cam.py`):** Uses `v4l2-ctl` with RAM-disk (`/dev/shm`) frame caching and a 5-second subprocess timeout to prevent USB camera hangs. Triggers a **5-shot burst** (3-second interval) followed by a **10-minute cooldown** to reduce false alarms and hardware wear.
* **Local AI Object Identification (`docker/object-detector/`):** A Dockerized YOLO watchdog monitors the `data/consume/` queue, identifies objects (e.g., `Person`, `Car`, `Couch`), and logs timestamped detections to `detection_log.csv` in local time (`TZ=America/New_York`).
* **Centralized Alerting Bus (`src/common/notifier.py`):** Zero-dependency Python standard-library SMTP/SSL dispatcher with overnight **quiet-hours** filtering (`11:00 PM – 6:00 AM`), JPEG attachment support, and isolated credentials in `~/.alert_env` (`chmod 600`).
* **Market & Index Monitor (`src/monitors/stock_monitor.py`):** Tracks major US indices (`^GSPC`, `^DJI`, `^IXIC`) and mega-cap stocks via Yahoo Finance with daily alert deduplication (`stock_alert_state.json`) and optional end-of-day summaries.
* **Streamlit Command Center (`src/dashboard/dashboard.py`):** Unified web UI displaying recent motion captures, AI vision detection logs, and system metrics.

---

## Architecture

```text
USB Webcam (/dev/video0)
   │  v4l2-ctl (MJPG -> /dev/shm/cam_frame.jpg)
   ▼
motion_cam.py (systemd) ──► /mnt/storage/motion_captures/ (NAS Archive)
   │                    ──► notifier.py (Quiet-Hours Email + JPEG)
   ▼
docker/object-detector/data/consume/
   │  YOLO AI Watchdog (Docker)
   ▼
docker/object-detector/data/processed/detection_log.csv
   │
   ▼
Streamlit Command Center (dashboard.py)

```

---

## Repository Structure

```text
local-ai-home-monitor/
├── config/
│   ├── alert_env.example              # Template for ~/.alert_env
│   ├── crontab.example                # Market-hours stock & sensor schedules
│   └── uvcvideo.conf                  # Kernel UVC quirks (quirks=128)
├── docker/
│   └── object-detector/
│       ├── docker-compose.yml         # YOLO watchdog service definition
│       ├── Dockerfile                 # Container build file
│       ├── app.py                     # YOLO inference & CSV logger
│       ├── asound.conf                # ALSA audio config
│       └── data/                      # consume/ and processed/ queues
├── services/
│   ├── motion-cam.service             # systemd unit for motion watcher
│   └── streamlit-dashboard.service    # systemd unit for dashboard UI
└── src/
    ├── common/notifier.py             # Reusable SSL email & quiet-hours module
    ├── vision/motion_cam.py           # V4L2 5-shot burst watcher
    ├── monitors/stock_monitor.py      # Yahoo Finance index & stock monitor
    └── dashboard/dashboard.py         # Streamlit Command Center

```

---

## Prerequisites

* **OS:** Ubuntu 22.04 / 24.04 LTS (or Debian-based Linux)
* **Hardware:** USB UVC webcam (`/dev/video0`) and local/NAS storage mount (`/mnt/storage`)
* **Packages:** `python3`, `python3-opencv`, `v4l-utils`, `docker`, `docker-compose-plugin`

```bash
sudo apt update
sudo apt install -y python3 python3-opencv v4l-utils
sudo usermod -aG video,docker $USER

```

---

## Quick Start

### 1. Configure USB Webcam Quirks (Optional)

For UVC 1.00 webcams (such as ANYKA chipsets) that suffer from MJPEG broken pipes or bandwidth allocation errors:

```bash
sudo cp config/uvcvideo.conf /etc/modprobe.d/uvcvideo.conf
sudo modprobe -r uvcvideo && sudo modprobe uvcvideo quirks=128

```

### 2. Set Up Credentials (`~/.alert_env`)

Use a dedicated server Gmail account with **2-Step Verification** enabled and a 16-character **Google App Password**:

```bash
cp config/alert_env.example ~/.alert_env
chmod 600 ~/.alert_env
nano ~/.alert_env

```

Verify email delivery:

```bash
python3 -s src/common/notifier.py

```

### 3. Start the Dockerized YOLO Watchdog

```bash
cd docker/object-detector
docker compose up -d
docker exec object-detector-ai-watchdog-1 date

```

### 4. Install `systemd` Services

Replace `<YOUR_USER>` in `services/*.service` with your Linux username, ensure `Environment="PYTHONPATH=/home/<YOUR_USER>/local-ai-home-monitor/src"` is set under `[Service]`, and enable the units:

```bash
sudo cp services/motion-cam.service /etc/systemd/system/
sudo cp services/streamlit-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now motion-cam streamlit-dashboard

```

### 5. Schedule Stock Monitoring via `cron`

Test the watchlist manually, then add the schedule from `config/crontab.example` to `crontab -e`:

```bash
PYTHONPATH=src python3 -s src/monitors/stock_monitor.py --summary
crontab -e

```

---

## Troubleshooting

| Issue | Likely Cause | Fix |
| --- | --- | --- |
| `/dev/shm/cam_frame.jpg` stuck at `0` bytes | USB webcam controller locked up | Run `sudo usbreset <vendor>:<product>` or replug the camera, then restart `motion-cam` |
| `Permission denied` on `/dev/video0` | User not in `video` group | Run `sudo usermod -aG video $USER` and re-login |
| `detection_log.csv` timestamps off by 5 hours | Docker container defaulting to UTC | Ensure `TZ=America/New_York` is set under `environment:` in `docker-compose.yml` |
| `SMTPAuthenticationError (535)` | Standard Gmail password used | Generate a 16-character App Password and update `SMTP_PASS` in `~/.alert_env` |
| `ModuleNotFoundError: common` | `PYTHONPATH` not set for `cron`/`systemd` | Point `PYTHONPATH` to `<repo>/src` |

---

## Security Notes

* Never commit `~/.alert_env`, `*.csv` logs, or captured `.jpg` media—all are excluded by `.gitignore`.
* Always run `chmod 600 ~/.alert_env` so only the service user can read SMTP credentials.

## License

MIT License

```

