from pathlib import Path

from sap_ff_reviewer.engine import ReviewEngine
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
        "end_time": "2026-05-12T13:00:00Z",
        "reason_code": "Investigated failed payment run per INC1234567",
        "ticket_reference": "INC1234567",
        "transaction_log": [{"timestamp": "2026-05-12T12:05:00Z", "tcode": "F110"}],
        "change_log": [],
        "system_log": [],
        "os_command_log": [],
    }
    if overrides:
        payload.update(overrides)
    return SessionParser().parse_dict(payload)


def test_review_session_returns_pass_when_no_findings():
    session = make_session()

    result = ReviewEngine().review_session(session)

    assert result.session_id == "FF-TEST-0001"
    assert result.verdict == "PASS"
    assert result.confidence == 0.9
    assert result.findings == []
    assert result.suggested_correction is None


def test_review_session_returns_needs_correction_for_weak_reason():
    session = make_session({"reason_code": "fix"})

    result = ReviewEngine().review_session(session)

    assert result.verdict == "NEEDS_CORRECTION"
    assert result.suggested_correction is not None
    assert {finding.rule_id for finding in result.findings} == {"R-001"}


def test_review_session_returns_reject_for_os_command():
    session = make_session({"os_command_log": [{"timestamp": "2026-05-12T12:10:00Z", "command": "whoami"}]})

    result = ReviewEngine().review_session(session)

    assert result.verdict == "REJECT"
    assert result.suggested_correction is None
    assert {finding.rule_id for finding in result.findings} == {"R-005"}


def test_review_file_returns_review_result():
    session_path = Path(__file__).parent / "fixtures" / "valid_session.json"

    result = ReviewEngine().review_file(session_path)

    assert result.session_id == "FF-TEST-0001"
    assert result.verdict == "PASS"
