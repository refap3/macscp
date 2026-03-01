"""Manages saved SSH sessions."""

import json
import os

SESSIONS_FILE = os.path.expanduser("~/.macscp/sessions.json")


class SavedSession:
    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        username: str,
        auth_type: str = "password",
        key_file: str = "",
    ):
        self.name = name
        self.host = host
        self.port = port
        self.username = username
        self.auth_type = auth_type  # "password" or "key"
        self.key_file = key_file

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "auth_type": self.auth_type,
            "key_file": self.key_file,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SavedSession":
        return cls(
            name=d.get("name", d.get("host", "")),
            host=d["host"],
            port=d.get("port", 22),
            username=d.get("username", ""),
            auth_type=d.get("auth_type", "password"),
            key_file=d.get("key_file", ""),
        )

    def __str__(self) -> str:
        return self.name or f"{self.username}@{self.host}"


class SessionManager:
    def __init__(self):
        self._sessions: list[SavedSession] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(SESSIONS_FILE):
            return
        try:
            with open(SESSIONS_FILE) as f:
                data = json.load(f)
            self._sessions = [SavedSession.from_dict(d) for d in data]
        except Exception:
            self._sessions = []

    def save(self) -> None:
        os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
        try:
            with open(SESSIONS_FILE, "w") as f:
                json.dump([s.to_dict() for s in self._sessions], f, indent=2)
        except Exception:
            pass

    @property
    def sessions(self) -> list[SavedSession]:
        return list(self._sessions)

    def add_or_update(self, session: SavedSession) -> None:
        for i, s in enumerate(self._sessions):
            if s.host == session.host and s.username == session.username:
                self._sessions[i] = session
                self.save()
                return
        self._sessions.append(session)
        self.save()

    def delete(self, index: int) -> None:
        if 0 <= index < len(self._sessions):
            self._sessions.pop(index)
            self.save()
