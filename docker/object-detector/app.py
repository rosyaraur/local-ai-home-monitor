import time
import os
import shutil
import csv
import pyttsx3
from datetime import datetime
from ultralytics import YOLO
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

CONSUME_DIR = "/app/data/consume"
PROCESSED_DIR = "/app/data/processed"
LOG_FILE = "/app/data/processed/detection_log.csv"

os.makedirs(CONSUME_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Time", "Object Detected", "Probability"])

print("Initializing Offline Voice Engine...")
engine = pyttsx3.init()
engine.setProperty('rate', 150)

def speak(text):
    print(f"Speaking: {text}")
    engine.say(text)
    engine.runAndWait()

print("Loading YOLO AI Model (CPU-Only)...")
model = YOLO('yolov8n.pt')
print(f"Monitoring {CONSUME_DIR} for new JPEG images...\n")

class ImageHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        
        filepath = event.src_path
        
        if filepath.lower().endswith(('.png', '.jpg', '.jpeg')):
            filename = os.path.basename(filepath)
            print(f"\nIncoming image detected: {filename}")
            
            time.sleep(1) 
            
            try:
                results = model(filepath)
                detected_objects = set()
                
                with open(LOG_FILE, mode='a', newline='') as f:
                    writer = csv.writer(f)
                    now = datetime.now()
                    date_str = now.strftime("%Y-%m-%d")
                    time_str = now.strftime("%H:%M:%S")

                    print("--- Objects Detected ---")
                    for result in results:
                        for box in result.boxes:
                            conf = float(box.conf)
                            if conf > 0.50: 
                                obj_name = model.names[int(box.cls)].capitalize()
                                detected_objects.add(obj_name)
                                print(f"- {obj_name} (Confidence: {conf:.2f})")
                                writer.writerow([date_str, time_str, obj_name, f"{conf:.2f}"])
                    print("------------------------")
                
                # Announce the detections out loud
                if detected_objects:
                    items_str = " and a ".join(list(detected_objects))
                    speak(f"Camera detected a {items_str}.")
                
                dest_path = os.path.join(PROCESSED_DIR, filename)
                shutil.move(filepath, dest_path)
                print(f"Archived {filename} to processed folder.\n")
                
            except Exception as e:
                print(f"Error processing {filename}: {e}")

observer = Observer()
observer.schedule(ImageHandler(), path=CONSUME_DIR, recursive=False)
observer.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()
observer.join()
