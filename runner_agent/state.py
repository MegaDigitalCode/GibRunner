import threading
import time
from dataclasses import dataclass, field


@dataclass
class SessionState:
    duration: int = 0
    start_time: float | None = None
    active: bool = True
    session_started: bool = False
    endpoints_sent: bool = False
    rustdesk_id: str | None = None
    rustdesk_password: str | None = None
    tmate_ssh: str | None = None
    tmate_web: str | None = None
    error: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def set_duration(self, minutes: int) -> None:
        with self.lock:
            self.duration = minutes
            self.start_time = time.time()

    def extend(self, minutes: int) -> int:
        with self.lock:
            self.duration += minutes
            return self.duration

    def remaining_minutes(self) -> int | None:
        with self.lock:
            if self.start_time is None or self.duration <= 0:
                return None
            elapsed = (time.time() - self.start_time) / 60
            return int(self.duration - elapsed)

    def mark_started(self) -> None:
        with self.lock:
            self.session_started = True

    def set_endpoints(self, rustdesk_id: str, rustdesk_password: str, tmate_ssh: str | None, tmate_web: str | None) -> None:
        with self.lock:
            self.rustdesk_id = rustdesk_id
            self.rustdesk_password = rustdesk_password
            self.tmate_ssh = tmate_ssh
            self.tmate_web = tmate_web
            self.endpoints_sent = True

    def stop(self) -> None:
        with self.lock:
            self.active = False
