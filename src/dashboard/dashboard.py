import streamlit as st
import psutil
import docker
import pandas as pd
import datetime
import glob
import os
import subprocess

# --- Page Config ---
st.set_page_config(page_title="Home Server Command Center", page_icon="🖥️", layout="wide")
st.title("🖥️ Home Server Command Center")
st.markdown("Live telemetry and job monitoring for the Beelink Ubuntu Node.")

if st.button("🔄 Refresh Data"):
    st.rerun()

st.markdown("---")

# --- Hardware Health Telemetry ---
st.header("⚙️ Hardware Health")
col1, col2, col3, col4, col5 = st.columns(5)

# CPU
cpu_percent = psutil.cpu_percent(interval=0.5)
col1.metric("CPU Usage", f"{cpu_percent}%")

# CPU Temperature
try:
    temps = psutil.sensors_temperatures()
    # Intel/Beelink uses 'coretemp', Raspberry Pi uses 'cpu_thermal'
    if 'coretemp' in temps:
        cpu_temp = temps['coretemp'][0].current
    elif 'cpu_thermal' in temps:
        cpu_temp = temps['cpu_thermal'][0].current
    elif temps:  # Fallback to any available sensor
        cpu_temp = list(temps.values())[0][0].current
    else:
        cpu_temp = None

    temp_str = f"{cpu_temp}°C" if cpu_temp else "N/A"
except Exception:
    temp_str = "Error"
col2.metric("CPU Temp", temp_str)

# Memory
ram = psutil.virtual_memory()
ram_total_gb = ram.total / (1024**3)
ram_used_gb = ram.used / (1024**3)
col3.metric("Memory Usage", f"{ram.percent}%", f"{ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB")

# Disk Space (Root)
disk = psutil.disk_usage('/')
disk_total_gb = disk.total / (1024**3)
disk_free_gb = disk.free / (1024**3)
col4.metric("Root Storage", f"{disk.percent}%", f"{disk_free_gb:.1f} GB Free")

# NAS Storage (If mounted via Samba/MergerFS)
nas_path = "/mnt/storage"
if os.path.exists(nas_path):
    nas = psutil.disk_usage(nas_path)
    nas_free_tb = nas.free / (1024**4)
    col5.metric("NAS Storage Pool", f"{nas.percent}%", f"{nas_free_tb:.2f} TB Free")
else:
    col5.metric("NAS Storage Pool", "Disconnected")

st.markdown("---")

# --- Docker AI Jobs Monitor ---
st.header("🐳 Containerized AI Jobs")
try:
    client = docker.from_env()
    containers = client.containers.list(all=True)

    if containers:
        container_data = []
        for c in containers:
            status_emoji = "🟢 Up" if c.status == "running" else f"🔴 {c.status.capitalize()}"
            container_data.append({
                "Service Name": c.name,
                "Status": status_emoji,
                "Image": c.image.tags[0] if c.image.tags else "Untagged",
                "Created": c.attrs['Created'][:10]
            })

        df_containers = pd.DataFrame(container_data)
        st.dataframe(df_containers, use_container_width=True, hide_index=True)
    else:
        st.info("No Docker containers found.")
except Exception as e:
    st.error(f"Could not connect to Docker Daemon. Ensure user is in docker group. Error: {e}")

st.markdown("---")

# --- Cron / File Watcher Monitors ---
st.header("📂 Recent Job Outputs")
col_log1, col_log2 = st.columns(2)

with col_log1:
    st.subheader("Job Scraper Logs")
    job_dir = "/mnt/storage/jobdatabase"
    if os.path.exists(job_dir):
        files = sorted(os.listdir(job_dir), reverse=True)[:5]
        if files:
            for f in files:
                st.text(f"📄 {f}")
        else:
            st.text("No scraped jobs found yet.")
    else:
        st.text("Job directory not mounted or missing.")

with col_log2:
    st.subheader("AI Vision Detections")
    vision_log = "/home/<YOUR_USER>/object-detector/data/processed/detection_log.csv"
    if os.path.exists(vision_log):
        try:
            df_vision = pd.read_csv(vision_log).tail(5)
            st.dataframe(df_vision, use_container_width=True, hide_index=True)
        except Exception:
            st.text("Error reading detection log.")
    else:
        st.text("No vision logs recorded yet.")

st.markdown("---")

# --- Motion Camera Monitor ---
st.header("📸 Motion Camera Monitor")
capture_dir = "/mnt/storage/motion_captures"
cam_state = subprocess.getoutput("systemctl is-active motion-cam").strip()

col_cam1, col_cam2, col_cam3 = st.columns(3)
col_cam1.metric(
    "Camera Service",
    "🟢 Active" if cam_state == "active" else f"🔴 {cam_state.capitalize() or 'Unknown'}"
)

captures = sorted(
    glob.glob(os.path.join(capture_dir, "motion_*.jpg")),
    key=os.path.getmtime,
    reverse=True
) if os.path.exists(capture_dir) else []

col_cam2.metric("Total Captures", len(captures))

if captures:
    latest_img = captures[0]
    latest_ts = datetime.datetime.fromtimestamp(os.path.getmtime(latest_img)).strftime("%Y-%m-%d %H:%M:%S")
    col_cam3.metric("Last Motion Event", latest_ts)

    st.image(latest_img, caption=f"Latest Capture: {os.path.basename(latest_img)}", use_container_width=True)

    if len(captures) > 1:
        with st.expander("View Recent Captures (Last 4)"):
            thumb_cols = st.columns(4)
            for idx, img_path in enumerate(captures[:4]):
                ts_label = datetime.datetime.fromtimestamp(os.path.getmtime(img_path)).strftime("%m-%d %H:%M:%S")
                thumb_cols[idx].image(img_path, caption=ts_label, use_container_width=True)
else:
    col_cam3.metric("Last Motion Event", "None")
    if os.path.exists(capture_dir):
        st.info("No motion captures found yet in `/mnt/storage/motion_captures`.")
    else:
        st.warning("Capture directory `/mnt/storage/motion_captures` is not mounted or missing.")

recent_cam_logs = subprocess.getoutput("journalctl -u motion-cam -n 10 --no-pager")
with st.expander("View Recent Motion Camera Logs"):
    st.code(recent_cam_logs, language="bash")

st.markdown("---")

# --- Scheduled Jobs & Background Services ---
st.header("🕰️ Scheduled Jobs & Background Services")
col_jobs1, col_jobs2 = st.columns(2)

with col_jobs1:
    st.subheader("⏱️ User Cron Jobs")
    try:
        cron_jobs = subprocess.getoutput('crontab -l')
        active_crons = [line for line in cron_jobs.split('\n') if line.strip() and not line.startswith('#')]

        if active_crons and "no crontab for" not in cron_jobs.lower():
            df_cron = pd.DataFrame(active_crons, columns=["Cron Schedule & Command"])
            st.dataframe(df_cron, use_container_width=True, hide_index=True)
        else:
            st.info("No active cron jobs found for user.")
    except Exception as e:
        st.error(f"Could not read crontab: {e}")

with col_jobs2:
    st.subheader("🤖 Custom Systemd Services")
    try:
        # Dynamically discover services built by the user in /etc/systemd/system/
        find_cmd = "find /etc/systemd/system/ -maxdepth 1 -name '*.service' -exec basename {} \\;"
        custom_svcs = [s for s in subprocess.getoutput(find_cmd).split('\n') if s.strip()]

        if custom_svcs and "No such file" not in custom_svcs[0]:
            svc_data = []
            for svc in sorted(custom_svcs):
                # Filter out standard OS symlinks
                if svc in ['dbus-org.freedesktop.resolve1.service', 'syslog.service']:
                    continue

                is_active = subprocess.getoutput(f"systemctl is-active {svc}").strip()
                emoji = "🟢 Active" if is_active == "active" else ("🟡 Failed" if is_active == "failed" else f"🔴 {is_active.capitalize()}")
                svc_data.append({"Service Name": svc, "Status": emoji})

            if svc_data:
                df_svc = pd.DataFrame(svc_data)
                st.dataframe(df_svc, use_container_width=True, hide_index=True)
            else:
                st.info("No custom systemd services found.")
        else:
            st.info("No custom systemd services found.")
    except Exception as e:
        st.error(f"Could not read systemd services: {e}")

st.markdown("---")

# --- Security & Access Logs ---
st.header("🔐 Security & SSH Access")
col_sec1, col_sec2 = st.columns(2)

try:
    invalid_attempts = subprocess.getoutput('journalctl -u ssh | grep -c "invalid user"')
    successful_logins = subprocess.getoutput('journalctl -u ssh | grep -c "Accepted"')

    col_sec1.metric("Blocked Unauthorized Attempts", invalid_attempts)
    col_sec2.metric("Successful Logins", successful_logins)

    st.subheader("🕵️ Username Login Attempts (Last 2000 Logs)")
    raw_logs = subprocess.getoutput('journalctl -u ssh -n 2000 --no-pager')

    user_counts = {}
    for line in raw_logs.split('\n'):
        if "invalid user" in line.lower():
            try:
                user = line.lower().split("user ")[1].split(" ")[0]
                user_counts[user] = user_counts.get(user, 0) + 1
            except IndexError:
                pass
        elif "Accepted" in line:
            try:
                user = line.split("for ")[1].split(" ")[0]
                user_counts[user] = user_counts.get(user, 0) + 1
            except IndexError:
                pass

    if user_counts:
        df_users = pd.DataFrame(list(user_counts.items()), columns=["Username", "Attempts"])
        df_users = df_users.sort_values(by="Attempts", ascending=False).reset_index(drop=True)
        st.dataframe(df_users, use_container_width=True, hide_index=True)
    else:
        st.info("No username attempts found in recent logs.")

    recent_ssh = subprocess.getoutput('journalctl -u ssh -n 5 --no-pager')
    with st.expander("View Recent SSH Terminal Logs"):
        st.code(recent_ssh, language="bash")

except Exception as e:
    st.error(f"Could not read SSH logs: {e}")
