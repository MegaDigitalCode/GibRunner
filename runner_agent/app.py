import platform
import threading
import time
import sys

import psutil

from .config import Config
from .state import SessionState
from .worker_client import WorkerClient
from .runtime import get_server_details, perform_system_shutdown, start_remote_access

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

TEXTS = {
    'en': {
        'start': "👋 **Runner Ready**\n\nRustDesk session will be prepared on this machine.\nSelect duration to start:",
        'starting': "🚀 **Starting Remote Access...**\nPlease wait (RustDesk + tmate setup)...",
        'active_text': "🖥️ **SESSION READY**\n\n📍 **Location:** {country} ({ip})\n⚙️ **Specs:** {cpu} Cores / {ram}GB RAM\n💻 **OS:** {os}\n\nRustDesk and SSH endpoint have been sent via bot backend.",
        'timeout': "🛑 Duration limit reached. Shutting down session.",
        'max_limit': "⚠️ **Max Limit!** Cannot exceed 6 Hours.",
        'status_info': "📊 **System Status**\nCPU: {cpu}%\nRAM: {ram}%\nTime Left: {left}m",
        'not_started': "⏳ Session has not started yet. Choose a duration first.",
        'already_starting': "⏳ Session is already starting/running.",
        'error': "❌ Error: {error}",
    }
}


def t(cfg: Config, key: str) -> str:
    return TEXTS.get(cfg.user_lang, TEXTS['en']).get(key, key)


def get_control_menu():
    return {
        "inline_keyboard": [[
            {"text": "📊 Info", "callback_data": "info"},
            {"text": "➕ Extend 30m", "callback_data": "extend"},
            {"text": "💀 KILL SESSION", "callback_data": "kill"},
        ]]
    }


def get_duration_menu():
    return {
        "inline_keyboard": [[
            {"text": "1 Hour", "callback_data": "time_60"},
            {"text": "2 Hours", "callback_data": "time_120"},
            {"text": "3 Hours", "callback_data": "time_180"},
            {"text": "4 Hours", "callback_data": "time_240"},
            {"text": "5 Hours", "callback_data": "time_300"},
            {"text": "6 Hours", "callback_data": "time_360"},
        ]]
    }


class RunnerAgentApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = SessionState()
        self.worker = WorkerClient(cfg.worker_url, cfg.runner_secret, cfg.chat_id, cfg.run_id)
        self._session_thread = None

    def is_web_mode(self) -> bool:
        # Web-only sessions use synthetic owner refs like "web:<user_id>".
        # In this mode there is no Telegram callback flow, so session start must
        # be automatic instead of waiting for button commands.
        return str(self.cfg.chat_id or "").startswith("web:")

    def safe_send(self, text, reply_markup=None):
        try:
            self.worker.send_bot_message(text, reply_markup=reply_markup)
        except Exception:
            pass

    def register_session(self):
        try:
            self.worker.register_session()
        except Exception:
            pass

    def stop_session_in_worker(self):
        try:
            self.worker.stop_session()
        except Exception:
            pass

    def send_endpoint_to_worker(self, endpoint_payload: dict):
        payload = {
            "os_type": "windows" if self.cfg.system_os == "Windows" else "ubuntu",
            "rustdesk_id": endpoint_payload.get("rustdesk_id"),
            "rustdesk_password": endpoint_payload.get("rustdesk_password"),
            "tmate_ssh": endpoint_payload.get("tmate_ssh"),
            "tmate_web": endpoint_payload.get("tmate_web"),
        }
        self.worker.send_session_endpoint(payload)

    def process_text(self, text: str):
        text = text.strip()
        if text in ("/panel", "/menu"):
            self.safe_send("🎛️ **Control Panel:**", reply_markup=get_control_menu())
            return
        if text.startswith('/'):
            return
        # No CRD/PIN flow anymore. Ignore plain text to avoid leaking secrets.

    def process_callback(self, data: str):
        if data.startswith("time_"):
            mins = int(data.split("_")[1])
            if mins > self.cfg.max_duration_minutes:
                self.safe_send(t(self.cfg, 'max_limit'))
                return
            with self.state.lock:
                if self.state.session_started or self._session_thread:
                    self.safe_send(t(self.cfg, 'already_starting'))
                    return
                self.state.set_duration(mins)
            self.safe_send(t(self.cfg, 'starting'))
            self._session_thread = threading.Thread(target=self.run_session_process, daemon=True)
            self._session_thread.start()
            return

        if data == "extend":
            if self.state.start_time is None:
                self.safe_send(t(self.cfg, 'not_started'))
                return
            with self.state.lock:
                if self.state.duration + 30 > self.cfg.max_duration_minutes:
                    self.safe_send(t(self.cfg, 'max_limit'))
                else:
                    self.state.extend(30)
                    self.safe_send("✅ +30 Mins", reply_markup=get_control_menu())
            return

        if data == "info":
            remaining = self.state.remaining_minutes()
            if remaining is None:
                self.safe_send(t(self.cfg, 'not_started'), reply_markup=get_control_menu())
                return
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            msg = t(self.cfg, 'status_info').format(cpu=cpu, ram=ram, left=max(0, remaining))
            self.safe_send(msg, reply_markup=get_control_menu())
            return

        if data == "kill":
            self.safe_send("💀 Shutdown...", reply_markup=None)
            self.perform_shutdown()
            return

    def perform_shutdown(self):
        self.state.stop()
        self.stop_session_in_worker()
        time.sleep(2)
        perform_system_shutdown(self.cfg.system_os)

    def run_session_process(self):
        try:
            endpoint_payload = start_remote_access(self.cfg.system_os, self.cfg.rustdesk_password)
            self.state.mark_started()
            self.state.set_endpoints(
                endpoint_payload.get("rustdesk_id"),
                endpoint_payload.get("rustdesk_password"),
                endpoint_payload.get("tmate_ssh"),
                endpoint_payload.get("tmate_web"),
            )
            try:
                self.send_endpoint_to_worker(endpoint_payload)
            except Exception as exc:
                self.safe_send(t(self.cfg, 'error').format(error=f"Failed to send endpoint to worker: {exc}"))

            country, ip, cpu, ram, os_ver = get_server_details()
            msg_text = t(self.cfg, 'active_text').format(country=country, ip=ip, cpu=cpu, ram=ram, os=os_ver)
            self.safe_send(msg_text, reply_markup=get_control_menu())
            self.monitor_loop()
        except Exception as exc:
            self.safe_send(t(self.cfg, 'error').format(error=str(exc)))

    def monitor_loop(self):
        while self.state.active:
            remaining = self.state.remaining_minutes()
            if remaining is not None and remaining <= 0:
                self.safe_send(t(self.cfg, 'timeout'))
                self.perform_shutdown()
                break
            time.sleep(30)

    def poll_loop(self):
        self.register_session()
        if self.is_web_mode():
            with self.state.lock:
                if not self.state.session_started and not self._session_thread:
                    self.state.set_duration(self.cfg.max_duration_minutes)
                    self._session_thread = threading.Thread(target=self.run_session_process, daemon=True)
                    self._session_thread.start()
        else:
            self.safe_send(t(self.cfg, 'start'), reply_markup=get_duration_menu())
        try:
            self.worker.heartbeat(force=True)
        except Exception:
            pass

        while self.state.active:
            try:
                self.worker.heartbeat(force=False)
            except Exception:
                pass

            try:
                data = self.worker.poll_updates()
                if data and "payload" in data:
                    ctype = data.get("command_type")
                    payload = data.get("payload") or ""
                    log_payload = "***" if payload.isdigit() else payload
                    print(f"Recv: {ctype} -> {log_payload}")
                    if ctype == "text":
                        self.process_text(payload)
                    elif ctype == "callback":
                        self.process_callback(payload)
            except Exception:
                pass
            time.sleep(self.cfg.poll_seconds)


def main():
    cfg = Config.from_env()
    if not cfg.chat_id or not cfg.worker_url or not cfg.runner_secret:
        raise RuntimeError("Missing TG_CHATID, WORKER_URL, or SESSION_SECRET")
    app = RunnerAgentApp(cfg)
    app.poll_loop()


if __name__ == '__main__':
    main()
