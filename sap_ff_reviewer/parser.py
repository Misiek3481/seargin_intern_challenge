from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from sap_ff_reviewer.models import InvalidSessionError, Session

class SessionParser:
    """Parse and validate firefighter session JSON payloads."""

    REQUIRED_STRING_FIELDS = (
        "session_id",
        "firefighter_id",
        "firefighter_user",
        "controller",
        "system",
        "client",
        "start_time",
        "end_time",
        "reason_code",
        "ticket_reference",
    )

    LOG_FIELDS = (
        "transaction_log",
        "change_log",
        "system_log",
        "os_command_log",
    )

    def parse_file(self, path: str | Path) -> Session:
        """Load a session JSON file from disk and return a validated Session."""

        session_path = Path(path)

        try:
            with session_path.open(encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError as exc:
            raise InvalidSessionError(f"Session file does not exist: {session_path}") from exc
        except json.JSONDecodeError as exc:
            raise InvalidSessionError(f"Session file is not valid JSON: {session_path}") from exc

        return self.parse_dict(data)

    def parse_dict(self, data: dict[str, Any]) -> Session:
        """Validate a decoded session payload and convert it into a Session."""

        if not isinstance(data, dict):
            raise InvalidSessionError("Session payload must be a JSON object.")

        normalized = dict(data)
        self._validate_required_fields(normalized)
        self._normalize_log_fields(normalized)

        start_time = self._parse_timestamp(normalized["start_time"], "start_time")
        end_time = self._parse_timestamp(normalized["end_time"], "end_time")

        if end_time < start_time:
            raise InvalidSessionError("end_time cannot be earlier than start_time.")

        return Session(
            session_id=normalized["session_id"].strip(),
            firefighter_id=normalized["firefighter_id"].strip(),
            firefighter_user=normalized["firefighter_user"].strip(),
            controller=normalized["controller"].strip(),
            system=normalized["system"].strip(),
            client=normalized["client"].strip(),
            start_time=start_time,
            end_time=end_time,
            reason_code=normalized["reason_code"].strip(),
            ticket_reference=normalized["ticket_reference"].strip(),
            transaction_log=normalized["transaction_log"],
            change_log=normalized["change_log"],
            system_log=normalized["system_log"],
            os_command_log=normalized["os_command_log"],
            ticket_requester=self._optional_string(normalized.get("ticket_requester")),
            alert_source=self._optional_string(normalized.get("alert_source")),
            raw=normalized,
        )

    def _validate_required_fields(self, data: dict[str, Any]) -> None:
        missing = [field for field in self.REQUIRED_STRING_FIELDS if field not in data]
        if missing:
            raise InvalidSessionError(f"Session payload is missing required fields: {', '.join(missing)}")

        invalid = [ field for field in self.REQUIRED_STRING_FIELDS if not isinstance(data[field], str) ]
        if invalid:
            raise InvalidSessionError(f"Session fields must be strings: {', '.join(invalid)}")

    def _normalize_log_fields(self, data: dict[str, Any]) -> None:
        for field in self.LOG_FIELDS:
            value = data.get(field, [])
            if value is None:
                value = []

            if not isinstance(value, list):
                raise InvalidSessionError(f"{field} must be a list.")

            non_objects = [ index for index, item in enumerate(value) if not isinstance(item, dict) ]
            if non_objects: # checking if in log fields are only dictionaries
                first_index = non_objects[0]
                raise InvalidSessionError(f"{field}[{first_index}] must be a JSON object.")

            data[field] = value ## to change from None to []

    def _parse_timestamp(self, value: str, field_name: str) -> datetime:
        """Parse an ISO 8601 timestamp, accepting UTC values ending in Z."""

        try:
            normalized_value = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized_value)
        except ValueError as exc:
            raise InvalidSessionError(f"{field_name} must be a valid ISO 8601 timestamp.") from exc

    def _optional_string(self, value: Any) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise InvalidSessionError("Optional string fields must be strings.")

        stripped = value.strip()
        return stripped or None
