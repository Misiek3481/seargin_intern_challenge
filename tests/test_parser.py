from datetime import timezone
from pathlib import Path

import pytest

from sap_ff_reviewer.models import InvalidSessionError
from sap_ff_reviewer.parser import SessionParser


def valid_payload():
    return {
        "session_id": "FF-TEST-0001",
        "firefighter_id": "FF_FI_01",
        "firefighter_user": "JKOWALSKI",
        "controller": "RGRC",
        "system": "PRD-S4",
        "client": "ACME-DE",
        "start_time": "2026-05-12T12:35:53Z",
        "end_time": "2026-05-12T13:36:53Z",
        "reason_code": "Investigated failed payment run per INC1234567",
        "ticket_reference": "INC1234567",
        "transaction_log": [{"timestamp": "2026-05-12T12:45:52Z", "tcode": "F110"}],
        "change_log": [],
        "system_log": [],
        "os_command_log": [],
    }


def test_parse_valid_session_file():
    session_path = Path(__file__).parent / "fixtures" / "valid_session.json"
    parser = SessionParser()

    session = parser.parse_file(session_path)

    payload = valid_payload()
    assert session.session_id == payload["session_id"]
    assert session.firefighter_user == payload["firefighter_user"]
    assert session.start_time.tzinfo == timezone.utc
    assert len(session.transaction_log) == len(payload["transaction_log"])
    assert len(session.change_log) == len(payload["change_log"])


def test_missing_required_field_raises_error():
    payload = valid_payload()
    del payload["session_id"]

    with pytest.raises(InvalidSessionError, match="missing required fields"):
        SessionParser().parse_dict(payload)


def test_missing_log_field_defaults_to_empty_list():
    payload = valid_payload()
    del payload["os_command_log"]

    session = SessionParser().parse_dict(payload)

    assert session.os_command_log == []


def test_null_log_field_defaults_to_empty_list():
    payload = valid_payload()
    payload["system_log"] = None

    session = SessionParser().parse_dict(payload)

    assert session.system_log == []


def test_invalid_log_field_type_raises_error():
    payload = valid_payload()
    payload["transaction_log"] = "F110"

    with pytest.raises(InvalidSessionError, match="transaction_log must be a list"):
        SessionParser().parse_dict(payload)


def test_invalid_log_entry_type_raises_error():
    payload = valid_payload()
    payload["transaction_log"] = [{"tcode": "F110"}, "bad entry"]

    with pytest.raises(InvalidSessionError, match=r"transaction_log\[1\] must be a JSON object"):
        SessionParser().parse_dict(payload)


def test_invalid_timestamp_raises_error():
    payload = valid_payload()
    payload["start_time"] = "not-a-date"

    with pytest.raises(InvalidSessionError, match="start_time"):
        SessionParser().parse_dict(payload)


def test_end_time_before_start_time_raises_error():
    payload = valid_payload()
    payload["end_time"] = "2026-05-12T11:36:53Z"

    with pytest.raises(InvalidSessionError, match="end_time cannot be earlier"):
        SessionParser().parse_dict(payload)


def test_optional_string_fields_are_normalized():
    payload = valid_payload()
    payload["ticket_requester"] = "  JKOWALSKI  "
    payload["alert_source"] = "   "

    session = SessionParser().parse_dict(payload)

    assert session.ticket_requester == "JKOWALSKI"
    assert session.alert_source is None


def test_invalid_optional_string_field_type_raises_error():
    payload = valid_payload()
    payload["ticket_requester"] = 123

    with pytest.raises(InvalidSessionError, match="Optional string fields"):
        SessionParser().parse_dict(payload)
