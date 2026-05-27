from sap_ff_reviewer.features import FeatureExtractor
from sap_ff_reviewer.parser import SessionParser


def make_session(overrides=None):
    payload = {
        "session_id": "FF-TEST-0001",
        "firefighter_id": "FF_FI_01",
        "firefighter_user": "JKOWALSKI",
        "controller": "RGRC",
        "system": "PRD-S4",
        "client": "ACME-DE",
        "start_time": "2026-05-12T12:00:00Z",
        "end_time": "2026-05-12T13:30:00Z",
        "reason_code": " Investigated failed payment run per INC1234567 ",
        "ticket_reference": "INC1234567",
        "transaction_log": [
            {"timestamp": "2026-05-12T12:05:00Z", "tcode": " f110 "},
            {"timestamp": "2026-05-12T12:10:00Z", "tcode": "su53"},
            {"timestamp": "2026-05-12T12:15:00Z", "tcode": ""},
            {"timestamp": "2026-05-12T12:20:00Z"},
        ],
        "change_log": [
            {"timestamp": "2026-05-12T12:25:00Z", "table": " lfb1 "},
            {"timestamp": "2026-05-12T12:26:00Z", "table": "LFA1"},
            {"timestamp": "2026-05-12T12:27:00Z", "table": ""},
            {"timestamp": "2026-05-12T12:28:00Z"},
        ],
        "system_log": [],
        "os_command_log": [],
    }
    if overrides:
        payload.update(overrides)
    return SessionParser().parse_dict(payload)


def test_extracts_basic_session_features():
    session = make_session()

    features = FeatureExtractor().extract(session)

    assert features.reason == "Investigated failed payment run per INC1234567"
    assert features.reason_length == len(features.reason)
    assert features.has_ticket_reference is True
    assert features.duration_minutes == 90
    assert features.is_after_hours is False
    assert features.transaction_count == 4
    assert features.change_count == 4


def test_extracts_normalized_tcodes_and_changed_tables():
    session = make_session()

    features = FeatureExtractor().extract(session)

    assert features.tcodes == {"F110", "SU53"}
    assert features.changed_tables == {"LFB1", "LFA1"}


def test_detects_missing_ticket_reference():
    session = make_session({"ticket_reference": "   "})

    features = FeatureExtractor().extract(session)

    assert features.has_ticket_reference is False


def test_detects_after_hours_session():
    session = make_session({"start_time": "2026-05-12T20:00:00Z", "end_time": "2026-05-12T20:30:00Z"})

    features = FeatureExtractor().extract(session)

    assert features.is_after_hours is True


def test_detects_os_commands():
    session = make_session({"os_command_log": [{"timestamp": "2026-05-12T12:30:00Z", "command": "whoami"}]})

    features = FeatureExtractor().extract(session)

    assert features.has_os_commands is True


def test_detects_debug_activity_from_system_log():
    session = make_session({"system_log": [{"timestamp": "2026-05-12T12:30:00Z", "message": "Debug session started by JKOWALSKI"}]})

    features = FeatureExtractor().extract(session)

    assert features.has_debug_activity is True


def test_detects_firefighter_as_ticket_requester():
    session = make_session({"ticket_requester": "jkowalski"})

    features = FeatureExtractor().extract(session)

    assert features.firefighter_is_requester is True
