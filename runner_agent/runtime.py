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


def _summarize_proc(prefix: str, proc: subprocess.CompletedProcess):
    # Avoid leaking secrets while still surfacing Linux RustDesk CLI behavior.
    out = (proc.stdout or "").strip().replace("\n", " ")
    err = (proc.stderr or "").strip().replace("\n", " ")
    if len(out) > 180:
        out = out[:180] + "..."
    if len(err) > 180:
        err = err[:180] + "..."
    print(f"{prefix} rc={proc.returncode} stdout={out!r} stderr={err!r}")


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

    # RustDesk Linux package installs a system service. Configure password via
    # sudo first (service scope), then fallback to user scope for compatibility.
    try:
        svc = _run_quiet(["sudo", "-n", "systemctl", "restart", "rustdesk"], timeout=20)
        _summarize_proc("rustdesk service restart (pre)", svc)
    except Exception as exc:
        print(f"rustdesk service restart (pre) exception={exc}")

    # Start desktop app so a UI session is available on the virtual display.
    subprocess.Popen([rustdesk], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    pw_set = False
    last_proc = None
    password_cmds = [
        ["sudo", "-n", rustdesk, "--password", password],
        [rustdesk, "--password", password],
    ]
    for idx, cmd in enumerate(password_cmds, start=1):
        for attempt in range(1, 5):
            proc = subprocess.run(cmd, capture_output=True, text=True)
            last_proc = proc
            _summarize_proc(f"rustdesk password cmd#{idx} attempt#{attempt}", proc)
            if proc.returncode == 0:
                pw_set = True
                break
            time.sleep(2)
        if pw_set:
            break
    if not pw_set:
        if last_proc is not None:
            _summarize_proc("rustdesk password final", last_proc)
        raise RuntimeError("Failed to set RustDesk password on Linux")

    try:
        svc = _run_quiet(["sudo", "-n", "systemctl", "restart", "rustdesk"], timeout=20)
        _summarize_proc("rustdesk service restart (post)", svc)
    except Exception as exc:
        print(f"rustdesk service restart (post) exception={exc}")

    rid = ""
    get_id_cmds = [
        ["sudo", "-n", rustdesk, "--get-id"],
        [rustdesk, "--get-id"],
    ]
    for cmd in get_id_cmds:
        for _ in range(8):
            out = subprocess.run(cmd, capture_output=True, text=True)
            rid = (out.stdout or "").strip().splitlines()[0] if (out.stdout or "").strip() else ""
            if rid:
                print(f"rustdesk get-id via {'sudo' if cmd[0] == 'sudo' else 'user'} success")
                break
            time.sleep(2)
        if rid:
            break
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
