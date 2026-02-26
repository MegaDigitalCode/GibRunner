import os
import platform
import shutil
import subprocess
import time
import requests
import psutil


def get_server_details():
    try:
        ip_data = requests.get("http://ip-api.com/json", timeout=5).json()
        country = ip_data.get("country", "Unknown")
        ip = ip_data.get("query", "Unknown")
        cpu_count = psutil.cpu_count(logical=True)
        ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
        os_ver = f"{platform.system()} {platform.release()}"
        return country, ip, cpu_count, ram_gb, os_ver
    except Exception:
        return "Unknown", "Unknown", "Unknown", "Unknown", "Unknown"


def _run_quiet(cmd, shell=False, timeout=20):
    return subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)


def _start_rustdesk_windows(password: str):
    rustdesk = shutil.which("rustdesk")
    if not rustdesk:
        likely = r"C:\Program Files\RustDesk\rustdesk.exe"
        if os.path.exists(likely):
            rustdesk = likely
    if not rustdesk:
        raise RuntimeError("RustDesk executable not found")

    subprocess.run([rustdesk, "--password", password], capture_output=True, text=True)
    rid = ""
    for _ in range(8):
        out = subprocess.run([rustdesk, "--get-id"], capture_output=True, text=True)
        rid = (out.stdout or "").strip().splitlines()[0] if (out.stdout or "").strip() else ""
        if rid:
            break
        time.sleep(2)
    if not rid:
        raise RuntimeError("RustDesk ID not found")
    subprocess.Popen([rustdesk], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return rid


def _start_rustdesk_linux(password: str):
    rustdesk = shutil.which("rustdesk")
    if not rustdesk:
        raise RuntimeError("rustdesk is not installed")

    # Start the desktop app first, then apply unattended password with retries.
    # On Linux runners the first password set can race with startup/init.
    subprocess.Popen([rustdesk], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

    pw_set = False
    for _ in range(6):
        out = subprocess.run([rustdesk, "--password", password], capture_output=True, text=True)
        if out.returncode == 0:
            pw_set = True
            break
        time.sleep(2)
    if not pw_set:
        raise RuntimeError("Failed to set RustDesk password on Linux")

    rid = ""
    for _ in range(10):
        out = subprocess.run([rustdesk, "--get-id"], capture_output=True, text=True)
        rid = (out.stdout or "").strip().splitlines()[0] if (out.stdout or "").strip() else ""
        if rid:
            break
        time.sleep(2)
    if not rid:
        raise RuntimeError("RustDesk ID not found")
    return rid


def _start_tmate_linux():
    if not shutil.which("tmate"):
        return None, None

    sock = "/tmp/tmate-gibrunner.sock"
    try:
        subprocess.run(["tmate", "-S", sock, "kill-server"], capture_output=True, text=True, timeout=5)
    except Exception:
        pass
    subprocess.Popen(["tmate", "-S", sock, "new-session", "-d"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ssh_cmd = None
    web_url = None
    for _ in range(20):
        ssh_out = _run_quiet(["tmate", "-S", sock, "display", "-p", "#{tmate_ssh}"], timeout=10)
        web_out = _run_quiet(["tmate", "-S", sock, "display", "-p", "#{tmate_web}"], timeout=10)
        ssh_cmd = (ssh_out.stdout or "").strip() or None
        web_url = (web_out.stdout or "").strip() or None
        if ssh_cmd:
            break
        time.sleep(2)
    return ssh_cmd, web_url


def start_remote_access(system_os: str, rustdesk_password: str):
    if system_os == "Windows":
        rustdesk_id = _start_rustdesk_windows(rustdesk_password)
        tmate_ssh, tmate_web = None, None
    else:
        rustdesk_id = _start_rustdesk_linux(rustdesk_password)
        tmate_ssh, tmate_web = _start_tmate_linux()
    return {
        "rustdesk_id": rustdesk_id,
        "rustdesk_password": rustdesk_password,
        "tmate_ssh": tmate_ssh,
        "tmate_web": tmate_web,
    }


def perform_system_shutdown(system_os: str):
    if system_os == "Windows":
        os.system("shutdown /s /t 0")
    else:
        # GitHub Ubuntu runners run as sudo-enabled user.
        os.system("sudo shutdown now")
