from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class InvalidSessionError(ValueError):
    """Raised when an input JSON cannot be parsed as a firefighter session."""


@dataclass(frozen=True)
class Session:
    session_id: str
    firefighter_id: str
    firefighter_user: str
    controller: str
    system: str
    client: str
    start_time: datetime
    end_time: datetime
    reason_code: str
    ticket_reference: str
    transaction_log: list[dict[str, Any]] = field(default_factory=list)
    change_log: list[dict[str, Any]] = field(default_factory=list)
    system_log: list[dict[str, Any]] = field(default_factory=list)
    os_command_log: list[dict[str, Any]] = field(default_factory=list)
    ticket_requester: str | None = None
    alert_source: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
