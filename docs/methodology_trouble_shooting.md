# Methodology, Tips & Tricks, and Troubleshooting Guide

This document details the engineering rationale behind the **Local AI Home Monitor** pipeline, practical optimizations for 24/7 headless Linux operation, and fixes for common hardware, kernel, Docker, and networking bugs.

---

## 1. System Methodology

### 1.1 Hardware-Safe Frame Acquisition (`v4l2-ctl` + RAM Disk)

Continuous OpenCV `cv2.VideoCapture(0)` loops frequently stall or throw MJPEG Huffman-table / broken-pipe errors on budget UVC 1.00 USB webcams (such as ANYKA chipsets). To avoid holding an unstable video handle open indefinitely, `motion_cam.py` uses single-shot CLI captures via `v4l2-ctl` (`--stream-mmap --stream-count=1`) at `1920x1080` MJPG:

* **Kernel Quirk Mitigation:** Loading `uvcvideo` with `quirks=128` (`0x80`, `UVC_QUIRK_FIX_BANDWIDTH`) overrides misreported USB bandwidth reservations from non-compliant camera firmware.
* **Subprocess Timeout Guard:** Every `v4l2-ctl` call is wrapped in `subprocess.run(..., timeout=5)` so a locked USB controller raises `subprocess.TimeoutExpired` instead of freezing the watcher thread permanently.


* **Zero-Wear RAM Caching:** Frames are written to `/dev/shm/cam_frame.jpg` (Linux `tmpfs` RAM disk) every second rather than to the SSD or USB NAS. Only confirmed motion events are copied to `/mnt/storage/motion_captures`.



### 1.2 Lightweight Motion Detection (OpenCV Frame Differencing)

Running YOLO inference on every 1080p frame wastes CPU on static scenes. Instead, `motion_cam.py` acts as a low-CPU gatekeeper using classical frame differencing:

1. **Downscaling:** Each 1080p frame is resized to `640x360` to cut pixel-processing cost by ~89%.


2. **Grayscale & Noise Suppression:** The frame is converted to grayscale and smoothed with a `21x21` Gaussian blur (`cv2.GaussianBlur`) to suppress sensor grain and minor flicker.


3. **Frame Differencing:** `cv2.absdiff(prev_gray, gray)` computes pixel-level changes against the prior frame.


4. **Thresholding & Dilation:** Differences above intensity `25` are binarized (`cv2.threshold`) and expanded with 2 dilation iterations (`cv2.dilate`) to merge fragmented moving regions into solid blobs.


5. **Contour Area Filtering:** `cv2.findContours` extracts external boundaries; motion is declared only if any contour exceeds `MIN_CONTOUR_AREA = 1500` pixels.



### 1.3 Burst Capture & Cooldown State Machine

To capture clear context without flooding storage or triggering endless alerts during prolonged activity, the watcher implements a deterministic burst-and-sleep cycle:

1. **Shot 1 (Immediate):** Copies `/dev/shm/cam_frame.jpg` (the frame that triggered motion) to both `/mnt/storage/motion_captures` and the AI consumer queue. During overnight quiet hours (`11:00 PM – 6:00 AM`), Shot 1 also dispatches a single email alert with the JPEG attached.


2. **Shots 2–5 (Burst):** Captures 4 additional frames spaced `BURST_INTERVAL = 3.0` seconds apart (`BURST_COUNT = 5`).


3. **Cooldown (`600` seconds):** Suspends polling for 10 minutes (`COOLDOWN_SEC = 600`), giving the USB camera controller idle recovery time.


4. **Baseline Reset:** Sets `prev_gray = None` upon waking so ambient lighting shifts (sunrise, clouds, lamps) during the 10-minute sleep do not immediately false-trigger a new burst.



### 1.4 Decoupled AI Object Identification (Producer–Consumer Pattern)

Rather than embedding PyTorch/YOLO inside the camera loop, inference is isolated in a Docker container (`ai-watchdog`, image `basic-detector`, `restart: unless-stopped`):

* **Queue Handoff:** `motion_cam.py` drops JPEGs into `./data/consume` (mounted to `/app/data/consume` inside the container).


* **Asynchronous Processing:** The container watches `/app/data/consume`, runs object detection, moves or archives processed images to `/app/data/processed`, and appends structured rows (`Date`, `Time`, `Object Detected`, `Probability`—e.g., `Person 0.81`, `Couch 0.68`, `Potted plant 0.55`) to `detection_log.csv`.


* **Fault Isolation:** If the Docker container restarts or is updated, `motion_cam.py` continues saving raw frames to the NAS without dropping a single event.



### 1.5 Centralized Alerting & Scheduled Monitors

* **Zero-Dependency Bus (`notifier.py`):** Uses only Python's standard library (`smtplib`, `email.message`, `mimetypes`) over SSL (port `465`) with credentials stored outside the codebase in `~/.alert_env` (`chmod 600`).
* **Market Monitor (`stock_monitor.py`):** Polls Yahoo Finance's chart API during US market hours via `cron`, percent-encodes index carets (`^GSPC`, `^DJI`, `^IXIC`), and tracks daily triggered rules in `stock_alert_state.json` to prevent duplicate emails.
* **Presentation Layer (`dashboard.py`):** Streamlit reads `detection_log.csv` and the NAS capture directory on demand, decoupling UI rendering from background collection.



---

## 2. Tips & Tricks

* **Run Services with `python3 -s`:** Passing `-s` ignores user-level `~/.local/lib/python3.*/site-packages`. This prevents `pip`-installed NumPy 2.x or OpenCV wheels from conflicting with Ubuntu's system `apt` package (`python3-opencv`).
* **Dispatch Emails in a Background Thread:** SMTP uploads with 1080p JPEG attachments take 1–3 seconds, which stretches the gap between Shot 1 and Shot 2. For exact 3-second burst intervals, wrap `send_alert` in a daemon thread:
```python
import threading
threading.Thread(target=send_alert, args=(subject, body, dest), daemon=True).start()

```


* **Plug the Webcam Directly into the Host:** Avoid unpowered USB hubs for UVC cameras. Direct motherboard ports (e.g., `usb 1-3` on `beelink-compute`) dramatically reduce USB disconnects and bandwidth contention.
* **Tune `MIN_CONTOUR_AREA` for Your Room:** `1500` works well at `640x360` for indoor rooms. Increase to `3000–5000` if curtains, pets, or shifting sunlight through windows cause false triggers; lower to `800` for distant entryways.


* **Set `PYTHONPATH` Once for Both `systemd` and `cron`:** Because `notifier.py` lives under `src/common/`, add `Environment="PYTHONPATH=/home/<YOUR_USER>/local-ai-home-monitor/src"` to `[Service]` in your `.service` files and `PYTHONPATH=...` at the top of `crontab -e`.
* **Create a Dedicated Gmail Filter:** Since all server alerts arrive from your dedicated server Gmail address, add a single Gmail filter (`from:your-server-email@gmail.com`) to auto-label messages `HomeServer` and mark `[Beelink URGENT]` or quiet-hours alerts as Important.
* **Keep `detection_log.csv` Clean:** Reset test entries while preserving the CSV header in one command:
```bash
head -n 1 ~/object-detector/data/processed/detection_log.csv > /tmp/hdr.csv && mv /tmp/hdr.csv ~/object-detector/data/processed/detection_log.csv

```



---

## 3. Potential Bugs, Root Causes, and Fixes

### 3.1 Camera & Linux Kernel Issues

| Symptom / Error | Root Cause | Fix |
| --- | --- | --- |
| `/dev/shm/cam_frame.jpg` frozen at `0` bytes; no new logs | USB webcam controller locked up; `v4l2-ctl` hung or timed out waiting for a frame

 | Stop `motion-cam`, run `sudo usbreset 04d6:e102` (or physically unplug/replug the camera for 5s), delete the `0`-byte file, and restart `motion-cam`. |
| `Failed to open /dev/video0: Permission denied` | Interactive user is not in the `video` group (even if `motion-cam.service` sets `Group=video`) | Run `sudo usermod -aG video $USER` and start a new SSH session. |
| `could not open /dev/shm/cam_frame.jpg for writing` when testing with `sudo` | Linux kernel `fs.protected_regular` (kernel 4.19+) blocks `root` from overwriting a file owned by another user in sticky directories like `/dev/shm` | Delete the user-owned file first (`sudo rm -f /dev/shm/cam_frame.jpg`), run the test, then delete the `root`-owned file before starting `motion-cam`. |
| Camera drops frames after USB reset on ANYKA UVC 1.00 | Driver drops incomplete MJPEG frames by default | Reload with `nodrop=1`: `sudo modprobe -r uvcvideo && sudo modprobe uvcvideo quirks=128 nodrop=1`. |
| Camera disappears or moves to `/dev/video2` after replug | Kernel assigned the next free V4L2 index while `/dev/video0` was still held open | Stop `motion-cam` before unplugging/replugging, or reference the camera via its persistent `/dev/v4l/by-id/...` symlink. |

### 3.2 Docker & YOLO Watchdog Issues

| Symptom / Error | Root Cause | Fix |
| --- | --- | --- |
| `detection_log.csv` timestamps are 5 hours ahead (UTC vs. EST) | Docker containers default to UTC | Add `TZ=America/New_York` under `environment:` in `docker-compose.yml` and recreate with `docker compose up -d`.

 |
| `docker compose up -d` fails with YAML validation error | `environment:` misaligned (e.g., 2 spaces instead of 4 under `ai-watchdog:`)

 | Align `environment:` directly under `volumes:` (4 spaces) and `- TZ=America/New_York` at 6 spaces.

 |
| `ALSA lib ... Unknown PCM default` / `aplay: audio open error` in `docker logs` | Offline voice announcement inside `basic-detector` cannot open an audio sink on a headless server

 | Harmless—does not affect YOLO inference or CSV logging. Silence by disabling TTS in `app.py` or pointing `asound.conf` to a `null` PCM device.

 |

### 3.3 Alerting, `systemd`, and `cron` Issues

| Symptom / Error | Root Cause | Fix |
| --- | --- | --- |
| `SMTPAuthenticationError: (535, ...)` | Standard Gmail password used instead of a 16-character App Password | Enable 2-Step Verification on the server Gmail account, generate an App Password at `[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)`, and update `SMTP_PASS` in `~/.alert_env`. |
| `Alert skipped: SMTP_USER or SMTP_PASS missing` | Script ran as `root`, so `os.path.expanduser("~/.alert_env")` resolved to `/root/.alert_env` | Set `User=<YOUR_USER>` in `systemd` units or use an absolute path in `ENV_PATH`. |
| `ModuleNotFoundError: No module named 'common'` | `systemd` or `cron` executed without `PYTHONPATH` pointing to `src/` | Add `Environment="PYTHONPATH=/home/<YOUR_USER>/local-ai-home-monitor/src"` to `.service` files and `PYTHONPATH=...` to `crontab -e`. |
| Quiet-hours alerts or `cron` jobs fire at the wrong time of day | Server OS timezone is UTC, or `cron` cached the old timezone before `timedatectl` was updated | Run `sudo timedatectl set-timezone America/New_York` and restart both `motion-cam` and `cron` (`sudo systemctl restart cron`). |
| `HTTP Error 400` on `^GSPC`, `^DJI`, or `^IXIC` in `stock_monitor.py` | Unencoded caret (`^`) in Yahoo Finance URL path | Encode symbols with `urllib.parse.quote(ticker, safe="")`. |
| `HTTP Error 429` or `403` from Yahoo Finance | Default `Python-urllib` User-Agent blocked or polling interval too aggressive | Keep `headers={"User-Agent": "Mozilla/5.0"}` and poll at `*/15` minutes or slower. |
| X-Sense mobile app constantly logs you out | X-Sense cloud permits only one active session per account | Create a secondary X-Sense account using the server email and share your home/devices from your primary account. |

---
