import os
import platform
import secrets
import string
from dataclasses import dataclass


def _gen_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def normalize_rustdesk_password(system_os: str, password: str | None) -> str:
    # RustDesk Linux unattended password handling is more reliable with 8-char
    # alphanumeric passwords (matches RustDesk's own Linux deployment examples).
    if not password:
        return _gen_password(12 if system_os == "Windows" else 8)
    cleaned = ''.join(ch for ch in password if ch.isalnum())
    if not cleaned:
        cleaned = _gen_password(12 if system_os == "Windows" else 8)
    if system_os == "Windows":
        return cleaned[:32]
    if len(cleaned) < 8:
        cleaned += _gen_password(8 - len(cleaned))
    return cleaned[:8]


@dataclass
class Config:
    chat_id: str
    worker_url: str
    user_lang: str
    system_os: str
    run_id: str | None
    rustdesk_password: str
    runner_secret: str
    heartbeat_seconds: int = 60
    poll_seconds: int = 2
    max_duration_minutes: int = 360

    @classmethod
    def from_env(cls) -> "Config":
        system_os = platform.system()
        return cls(
            chat_id=os.getenv('TG_CHATID', ''),
            worker_url=os.getenv('WORKER_URL', ''),
            user_lang=os.getenv('USER_LANG', 'en').lower(),
            system_os=system_os,
            run_id=os.getenv('GITHUB_RUN_ID'),
            rustdesk_password=normalize_rustdesk_password(system_os, os.getenv('RUSTDESK_PASSWORD')),
            runner_secret=os.getenv('SESSION_SECRET', ''),
        )
