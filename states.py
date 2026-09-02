from __future__ import annotations

from typing import Any


class SessionStore:
    """Short-lived conversational state for Telegram admin input flows."""

    def __init__(self) -> None:
        self._sessions: dict[int, dict[str, Any]] = {}

    def set(self, user_id: int, flow: str, **data: Any) -> None:
        self._sessions[user_id] = {"flow": flow, **data}

    def get(self, user_id: int) -> dict[str, Any] | None:
        return self._sessions.get(user_id)

    def pop(self, user_id: int) -> dict[str, Any] | None:
        return self._sessions.pop(user_id, None)
