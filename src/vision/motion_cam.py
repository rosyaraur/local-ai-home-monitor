import cv2
import os
import shutil
import subprocess
import time
from datetime import datetime

from common.notifier import is_quiet_hours, send_alert

OUT_DIR = "/mnt/storage/motion_captures"
CONSUME_DIR = "/home/<YOUR_USER>/object-detector/data/consume"
TMP_FRAME = "/dev/shm/cam_frame.jpg"

COOLDOWN_SEC = 600      # 10 minutes off after a burst
BURST_COUNT = 5         # Number of shots per motion event
BURST_INTERVAL = 3.0    # Seconds between burst shots
MIN_CONTOUR_AREA = 1500
CHECK_INTERVAL = 1.0    # Seconds between motion checks

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(CONSUME_DIR, exist_ok=True)
prev_gray = None


def capture_frame():
    cmd = [
        "v4l2-ctl",
        "--device=/dev/video0",
        "--set-fmt-video=width=1920,height=1080,pixelformat=MJPG",
        "--stream-mmap",
        "--stream-count=1",
        f"--stream-to={TMP_FRAME}",
    ]
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return res.returncode == 0 and os.path.exists(TMP_FRAME) and os.path.getsize(TMP_FRAME) > 0
    except subprocess.TimeoutExpired:
        print("Warning: v4l2-ctl timed out waiting for frame", flush=True)
        return False


def save_and_queue(shot_num):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"motion_{ts}.jpg"
    dest = os.path.join(OUT_DIR, filename)
    shutil.copy2(TMP_FRAME, dest)
    shutil.copy2(TMP_FRAME, os.path.join(CONSUME_DIR, filename))
    print(f"Motion burst ({shot_num}/{BURST_COUNT}) -> saved {dest} & queued for AI detector", flush=True)

    if shot_num == 1 and is_quiet_hours():
        send_alert(
            subject=f"[Beelink Alert] Quiet-Hours Motion Detected ({ts})",
            body=f"Unexpected motion detected on beelink-compute at {ts}.\nSaved to: {dest}",
            image_path=dest,
        )


print("Starting v4l2-ctl motion watcher...", flush=True)

while True:
    if not capture_frame():
        time.sleep(2)
        continue

    frame = cv2.imread(TMP_FRAME)
    if frame is None:
        time.sleep(CHECK_INTERVAL)
        continue

    small = cv2.resize(frame, (640, 360))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)

    if prev_gray is None:
        prev_gray = gray
        time.sleep(CHECK_INTERVAL)
        continue

    delta = cv2.absdiff(prev_gray, gray)
    thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    motion_detected = any(cv2.contourArea(c) > MIN_CONTOUR_AREA for c in contours)

    if motion_detected:
        # Shot 1 uses the frame that just triggered motion
        save_and_queue(1)

        # Shots 2 through 5 at 3-second intervals
        for shot in range(2, BURST_COUNT + 1):
            time.sleep(BURST_INTERVAL)
            if capture_frame():
                save_and_queue(shot)
            else:
                print(f"Motion burst ({shot}/{BURST_COUNT}) -> skipped (capture failed)", flush=True)

        print(f"Burst complete. Pausing camera for {COOLDOWN_SEC} seconds...", flush=True)
        time.sleep(COOLDOWN_SEC)
        prev_gray = None  # Reset baseline frame after waking up
        continue

    prev_gray = gray
    time.sleep(CHECK_INTERVAL)
