import time
import requests


class WorkerClient:
    def __init__(self, worker_url: str, bot_secret: str, chat_id: str, run_id: str | None):
        self.worker_url = worker_url.rstrip('/') if worker_url else ''
        self.bot_secret = bot_secret
        self.chat_id = chat_id
        self.run_id = run_id
        self._last_heartbeat = 0.0

    def register_session(self) -> None:
        if not (self.worker_url and self.run_id):
            return
        payload = {"chat_id": self.chat_id, "run_id": self.run_id, "secret": self.bot_secret}
        requests.post(f"{self.worker_url}/register-session", json=payload, timeout=10)

    def heartbeat(self, force: bool = False) -> None:
        if not (self.worker_url and self.run_id):
            return
        now = time.time()
        if not force and now - self._last_heartbeat < 60:
            return
        requests.post(
            f"{self.worker_url}/heartbeat",
            json={"run_id": self.run_id, "secret": self.bot_secret},
            timeout=5,
        )
        self._last_heartbeat = now

    def stop_session(self) -> None:
        if not self.worker_url:
            return
        payload = {"chat_id": self.chat_id, "secret": self.bot_secret}
        requests.post(f"{self.worker_url}/end-session", json=payload, timeout=5)

    def poll_updates(self) -> dict:
        if not self.worker_url:
            return {}
        headers = {"X-Bot-Secret": self.bot_secret}
        resp = requests.get(f"{self.worker_url}/get-updates?chat_id={self.chat_id}", headers=headers, timeout=10)
        try:
            return resp.json()
        except Exception:
            return {}

    def send_session_endpoint(self, payload: dict) -> None:
        if not self.worker_url:
            return
        body = {"chat_id": self.chat_id, "run_id": self.run_id, "secret": self.bot_secret, **payload}
        requests.post(f"{self.worker_url}/session-endpoint", json=body, timeout=10)

    def send_bot_message(self, text: str, reply_markup: dict | None = None) -> None:
        if not self.worker_url:
            return
        body = {
            "chat_id": self.chat_id,
            "run_id": self.run_id,
            "secret": self.bot_secret,
            "text": text,
        }
        if reply_markup:
            body["reply_markup"] = reply_markup
        requests.post(f"{self.worker_url}/runner-message", json=body, timeout=10)
