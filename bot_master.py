import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import subprocess
import time
import threading
import psutil
import sys
import requests 
import platform
import socket
import re # Tambahan untuk regex replace nama CRD

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

# --- CONFIG ---
TOKEN = os.getenv('TG_TOKEN')
CHAT_ID = os.getenv('TG_CHATID')
WORKER_URL = os.getenv('WORKER_URL')
USER_LANG = os.getenv('USER_LANG', 'en').lower()
SYSTEM_OS = platform.system()
RUN_ID = os.getenv('GITHUB_RUN_ID') 

# NAMA KOMPUTER YANG ANDA MINTA
CRD_NAME = "TryGitRDP - MegaDigital"

bot = telebot.TeleBot(TOKEN)

TEXTS = {
    'en': {
        'start': f"👋 **{SYSTEM_OS} RDP READY!**\n\nPaste **CRD Command** now.\n(From: remotedesktop.google.com/headless)",
        'cmd_received': "✅ Command OK. Name set to **" + CRD_NAME + "**\nInput **PIN (6 Digits)**:",
        'pin_ok': "✅ PIN Saved.\n👉 **Select Duration (Hours):**",
        'starting': "🚀 **Starting RDP...**\nPlease wait...",
        'active_text': "🖥️ **RDP ACTIVE!**\n\n📍 **Location:** {country} ({ip})\n⚙️ **Specs:** {cpu} Cores / {ram}GB RAM\n💻 **OS:** {os}\n\nLogin via Chrome Remote Desktop app now.",
        'timeout': "🛑 Duration Limit Reached.",
        'max_limit': "⚠️ **Max Limit!** Cannot exceed 6 Hours.",
        'status_info': "📊 **System Status**\nCPU: {cpu}%\nRAM: {ram}%\nTime Left: {left}m"
    },
    'id': {
        'start': f"👋 **{SYSTEM_OS} RDP SIAP!**\n\nPaste **Command CRD** sekarang.\n(Dari: remotedesktop.google.com/headless)",
        'cmd_received': "✅ Command Diterima. Nama set ke **" + CRD_NAME + "**\nMasukkan **PIN (6 Angka)**:",
        'pin_ok': "✅ PIN Disimpan.\n👉 **Pilih Durasi (Jam):**",
        'starting': "🚀 **Menyalakan RDP...**\nMohon tunggu...",
        'active_text': "🖥️ **RDP AKTIF!**\n\n📍 **Lokasi:** {country} ({ip})\n⚙️ **Spek:** {cpu} Core / {ram}GB RAM\n💻 **OS:** {os}\n\nSilakan Login di aplikasi CRD sekarang.",
        'timeout': "🛑 Batas Waktu Habis.",
        'max_limit': "⚠️ **Batas Max!** Tidak bisa lebih dari 6 Jam.",
        'status_info': "📊 **Status System**\nCPU: {cpu}%\nRAM: {ram}%\nSisa Waktu: {left}m"
    }
}
def t(key): return TEXTS.get(USER_LANG, TEXTS['en']).get(key, key)

state = {"crd_cmd": None, "pin": None, "duration": 0, "start_time": None, "active": True}

# --- MENU CONTROL ---
def get_control_menu():
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(
        InlineKeyboardButton("📊 Info", callback_data="info"),
        InlineKeyboardButton("➕ Extend 30m", callback_data="extend"),
        InlineKeyboardButton("💀 KILL RDP", callback_data="kill")
    )
    return mk

def get_server_details():
    try:
        ip_data = requests.get("http://ip-api.com/json").json()
        country = ip_data.get("country", "Unknown")
        ip = ip_data.get("query", "Unknown")
        cpu_count = psutil.cpu_count(logical=True)
        ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
        os_ver = f"{platform.system()} {platform.release()}"
        return country, ip, cpu_count, ram_gb, os_ver
    except:
        return "Unknown", "Unknown", "Unknown", "Unknown", "Unknown"

# --- NETWORK CALLS ---
def register_session():
    try:
        if RUN_ID and WORKER_URL:
            payload = {"chat_id": CHAT_ID, "run_id": RUN_ID, "secret": TOKEN}
            requests.post(f"{WORKER_URL}/register-session", json=payload, timeout=10)
    except: pass

# FUNGSI BARU: Hapus Sesi di Worker sebelum Shutdown
def stop_session_in_worker():
    try:
        if WORKER_URL:
            payload = {"chat_id": CHAT_ID, "secret": TOKEN}
            requests.post(f"{WORKER_URL}/end-session", json=payload, timeout=5)
    except: pass

def poll_cloudflare():
    register_session()
    print("Bot Started. Sending Greeting...")
    try: bot.send_message(CHAT_ID, t('start')) 
    except: pass

    while state["active"]:
        try:
            headers = {"X-Bot-Secret": TOKEN}
            resp = requests.get(f"{WORKER_URL}/get-updates?chat_id={CHAT_ID}", headers=headers, timeout=10)
            data = resp.json()
            if data and "payload" in data:
                ctype = data.get("command_type")
                payload = data.get("payload")
                
                log_p = payload
                if "--code=" in payload or (payload.isdigit() and len(payload)>=6): log_p = "***"
                print(f"📩 Recv: {ctype} -> {log_p}")
                
                if ctype == "text": process_text(payload)
                elif ctype == "callback": process_callback(payload)
        except: pass
        time.sleep(2)

def process_text(text):
    text = text.strip()
    
    if text == "/panel" or text == "/menu":
        bot.send_message(CHAT_ID, "🎛️ **Control Panel:**", reply_markup=get_control_menu())
        return

    if state["crd_cmd"] is None:
        if "--code=" in text:
            # INJEKSI NAMA KOMPUTER DI SINI
            final_cmd = text
            # Regex replace jika --name sudah ada
            if re.search(r'--name="[^"]+"', final_cmd):
                final_cmd = re.sub(r'--name="[^"]+"', f'--name="{CRD_NAME}"', final_cmd)
            # Regex replace jika --name tanpa kutip (jarang, tapi jaga-jaga)
            elif re.search(r'--name=[^\s]+', final_cmd):
                final_cmd = re.sub(r'--name=[^\s]+', f'--name="{CRD_NAME}"', final_cmd)
            else:
                # Append jika belum ada
                final_cmd += f' --name="{CRD_NAME}"'

            state["crd_cmd"] = final_cmd
            bot.send_message(CHAT_ID, t('cmd_received'))
        else:
            bot.send_message(CHAT_ID, "❌ Format CRD Salah (Pastikan ada --code).")
    elif state["pin"] is None:
        if text.isdigit() and len(text) >= 6:
            state["pin"] = text
            mk = InlineKeyboardMarkup(row_width=3)
            mk.add(
                InlineKeyboardButton("1 Jam", callback_data="time_60"),
                InlineKeyboardButton("2 Jam", callback_data="time_120"),
                InlineKeyboardButton("3 Jam", callback_data="time_180"),
                InlineKeyboardButton("4 Jam", callback_data="time_240"),
                InlineKeyboardButton("5 Jam", callback_data="time_300"),
                InlineKeyboardButton("6 Jam", callback_data="time_360")
            )
            bot.send_message(CHAT_ID, t('pin_ok'), reply_markup=mk)
        else:
            bot.send_message(CHAT_ID, "❌ PIN harus 6 angka.")

def process_callback(data):
    if data.startswith("time_"):
        mins = int(data.split("_")[1])
        state["duration"] = mins
        state["start_time"] = time.time()
        bot.send_message(CHAT_ID, t('starting'))
        threading.Thread(target=run_rdp_process).start()
        
    elif data == "extend":
        if state["duration"] + 30 > 360:
            bot.send_message(CHAT_ID, t('max_limit'))
        else:
            state["duration"] += 30
            bot.send_message(CHAT_ID, "✅ +30 Mins", reply_markup=get_control_menu())
    elif data == "info":
        elapsed = (time.time() - state["start_time"]) / 60
        left = int(state["duration"] - elapsed)
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        msg = t('status_info').format(cpu=cpu, ram=ram, left=left)
        bot.send_message(CHAT_ID, msg, reply_markup=get_control_menu())
    elif data == "kill": 
        bot.send_message(CHAT_ID, "💀 Shutdown...", reply_markup=None)
        perform_shutdown()

def perform_shutdown():
    state["active"] = False
    stop_session_in_worker() # LAPOR KE WORKER SEBELUM MATI
    time.sleep(2)
    if SYSTEM_OS == "Windows": os.system("shutdown /s /t 0")
    else: os.system("sudo shutdown now")

def run_rdp_process():
    try:
        cmd = state["crd_cmd"]
        pin = state["pin"]
        if SYSTEM_OS == "Windows":
            if 'remoting_start_host.exe"' in cmd:
                final = cmd.replace('remoting_start_host.exe"', f'remoting_start_host.exe" --pin="{pin}"')
            else: final = f'{cmd} --pin="{pin}"'
            subprocess.Popen(["powershell", "-Command", final], shell=True)
        else:
            final = f'{cmd} --pin="{pin}"'
            subprocess.Popen(final, shell=True, executable='/bin/bash')

        time.sleep(10)
        
        country, ip, cpu, ram, os_ver = get_server_details()
        msg_text = t('active_text').format(country=country, ip=ip, cpu=cpu, ram=ram, os=os_ver)
        
        bot.send_message(CHAT_ID, msg_text, reply_markup=get_control_menu())
        monitor_loop()
    except Exception as e:
        bot.send_message(CHAT_ID, f"Error: {e}")

def monitor_loop():
    while state["active"]:
        elapsed = (time.time() - state["start_time"]) / 60
        if (state["duration"] - elapsed) <= 0:
            bot.send_message(CHAT_ID, t('timeout'))
            perform_shutdown()
            break
        time.sleep(30)

if __name__ == "__main__":
    poll_cloudflare()
