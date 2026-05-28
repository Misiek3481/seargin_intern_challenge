from sap_ff_reviewer.correction import CorrectionBuilder
from sap_ff_reviewer.models import Finding
from sap_ff_reviewer.parser import SessionParser


def make_session(overrides=None):
    payload = {
        "session_id": "FF-TEST-0001",
        "firefighter_id": "FF_FI_01",
        "firefighter_user": "JKOWALSKI",
        "controller": "RGRC",
        "system": "PRD-S4",
        "client": "ACME-DE",
        "start_time": "2026-05-12T20:00:00Z",
        "end_time": "2026-05-12T20:30:00Z",
        "reason_code": "fix",
        "ticket_reference": "INC1234567",
        "transaction_log": [{"timestamp": "2026-05-12T20:05:00Z", "tcode": "F110"}],
        "change_log": [],
        "system_log": [],
        "os_command_log": [],
    }
    if overrides:
        payload.update(overrides)
    return SessionParser().parse_dict(payload)


def make_finding(rule_id, severity="medium", description="Test finding."):
    return Finding(
        rule_id=rule_id,
        severity=severity,
        location="reason_code",
        description=description,
        evidence="test evidence",
    )


def test_returns_none_when_verdict_does_not_need_correction():
    session = make_session()
    findings = [make_finding("R-001")]

    assert CorrectionBuilder().build(session, findings, "PASS") is None
    assert CorrectionBuilder().build(session, findings, "REJECT") is None


def test_builds_message_and_reason_rewrite_for_weak_reason():
    session = make_session()
    findings = [make_finding("R-001")]

    correction = CorrectionBuilder().build(session, findings, "NEEDS_CORRECTION")

    assert correction is not None
    assert "FF-TEST-0001" in correction.message_to_firefighter
    assert "more specific reason code" in correction.message_to_firefighter
    assert correction.suggested_reason_rewrite is not None
    assert "INC1234567" in correction.suggested_reason_rewrite
    assert "F110" in correction.suggested_reason_rewrite


def test_includes_after_hours_clarification_for_r007():
    session = make_session({"reason_code": "Routine check per CHG1234567"})
    findings = [make_finding("R-007")]

    correction = CorrectionBuilder().build(session, findings, "NEEDS_CORRECTION")

    assert correction is not None
    assert "outside business hours" in correction.message_to_firefighter
    assert correction.suggested_reason_rewrite is None


def test_includes_generic_clarification_for_unknown_correction_rule():
    session = make_session()
    findings = [make_finding("R-999", description="Custom issue requires clarification.")]

    correction = CorrectionBuilder().build(session, findings, "NEEDS_CORRECTION")

    assert correction is not None
    assert "R-999" in correction.message_to_firefighter
    assert "Custom issue requires clarification" in correction.message_to_firefighter
