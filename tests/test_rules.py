from sap_ff_reviewer.features import FeatureExtractor
from sap_ff_reviewer.parser import SessionParser
from sap_ff_reviewer.rules import (
    R001WeakReasonRule,
    R003DebugActivityRule,
    R004DirectTableModificationRule,
    R005OsCommandRule,
    R006ExcessiveChangeVolumeRule,
    R007AfterHoursWithoutEmergencyRule,
    R008SelfApprovalRule,
    R009LongSessionWithoutRejustificationRule,
    R010SodConflictRule,
    RuleEngine,
)


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


def extract_features(session):
    return FeatureExtractor().extract(session)


def test_r001_flags_empty_reason():
    session = make_session({"reason_code": "   "})
    features = extract_features(session)

    findings = R001WeakReasonRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-001"
    assert findings[0].severity == "medium"
    assert findings[0].location == "reason_code"


def test_r001_does_not_flag_specific_reason():
    session = make_session()
    features = extract_features(session)

    findings = R001WeakReasonRule().check(session, features)

    assert findings == []


def test_r003_flags_debug_activity():
    session = make_session({"system_log": [{"timestamp": "2026-05-12T12:10:00Z", "message": "Debug session started by JKOWALSKI", "type": "SM21"}]})
    features = extract_features(session)

    findings = R003DebugActivityRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-003"
    assert findings[0].severity == "critical"
    assert findings[0].location == "system_log[0]"
    assert "Debug session started" in findings[0].evidence


def test_r004_flags_direct_sensitive_table_modification_without_data_fix_reason():
    session = make_session({
        "reason_code": "Quick configuration check",
        "transaction_log": [{"tcode": "SE16N"}],
        "change_log": [{"table": "T001", "field": "WAERS", "old_value": "EUR", "new_value": "USD"}],
    })
    features = extract_features(session)

    findings = R004DirectTableModificationRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-004"
    assert findings[0].severity == "high"
    assert findings[0].location == "change_log"
    assert findings[0].evidence == "tcodes=SE16N; tables=T001"


def test_r004_does_not_flag_direct_table_modification_with_data_fix_reason():
    session = make_session({
        "reason_code": "Approved data fix for vendor bank data per CHG1234567",
        "transaction_log": [{"tcode": "SE16N"}],
        "change_log": [{"table": "LFBK", "field": "IBAN", "old_value": "A", "new_value": "B"}],
    })
    features = extract_features(session)

    findings = R004DirectTableModificationRule().check(session, features)

    assert findings == []


def test_r005_flags_os_command_execution():
    session = make_session({"os_command_log": [{"timestamp": "2026-05-12T12:10:00Z", "command": "whoami", "parameters": "-all"}]})
    features = extract_features(session)

    findings = R005OsCommandRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-005"
    assert findings[0].severity == "critical"
    assert findings[0].location == "os_command_log[0]"
    assert findings[0].evidence == "whoami -all"


def test_r006_flags_mass_change_volume():
    changes = [{"table": "LFA1", "key": str(index)} for index in range(200)]
    session = make_session({"change_log": changes})
    features = extract_features(session)

    findings = R006ExcessiveChangeVolumeRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-006"
    assert findings[0].severity == "high"
    assert "change_count=200" in findings[0].evidence


def test_r006_flags_many_changes_for_single_object_reason():
    changes = [{"table": "LFA1", "key": str(index)} for index in range(11)]
    session = make_session({"reason_code": "Fix one vendor blocked status", "change_log": changes})
    features = extract_features(session)

    findings = R006ExcessiveChangeVolumeRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-006"
    assert "single-object fix" in findings[0].description


def test_r006_does_not_flag_small_change_volume():
    changes = [{"table": "LFA1", "key": "100234"}]
    session = make_session({"reason_code": "Fix one vendor blocked status", "change_log": changes})
    features = extract_features(session)

    findings = R006ExcessiveChangeVolumeRule().check(session, features)

    assert findings == []


def test_r007_flags_after_hours_without_emergency_reason():
    session = make_session({"start_time": "2026-05-12T20:00:00Z", "end_time": "2026-05-12T20:30:00Z", "reason_code": "Routine configuration check per CHG1234567"})
    features = extract_features(session)

    findings = R007AfterHoursWithoutEmergencyRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-007"
    assert findings[0].severity == "medium"
    assert findings[0].location == "start_time"


def test_r007_does_not_flag_after_hours_emergency_reason():
    session = make_session({"start_time": "2026-05-12T20:00:00Z", "end_time": "2026-05-12T20:30:00Z", "reason_code": "Resolved failed production payment run per INC1234567"})
    features = extract_features(session)

    findings = R007AfterHoursWithoutEmergencyRule().check(session, features)

    assert findings == []


def test_r008_flags_firefighter_as_ticket_requester():
    session = make_session({"ticket_requester": "jkowalski"})
    features = extract_features(session)

    findings = R008SelfApprovalRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-008"
    assert findings[0].severity == "high"
    assert findings[0].location == "ticket_requester"


def test_r009_flags_long_session_without_rejustification():
    session = make_session({"start_time": "2026-05-12T10:00:00Z", "end_time": "2026-05-12T12:30:00Z"})
    features = extract_features(session)

    findings = R009LongSessionWithoutRejustificationRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-009"
    assert findings[0].severity == "medium"
    assert findings[0].location == "start_time/end_time"
    assert "duration_minutes=150" in findings[0].evidence


def test_r009_does_not_flag_long_session_with_rejustification():
    session = make_session({
        "start_time": "2026-05-12T10:00:00Z",
        "end_time": "2026-05-12T12:30:00Z",
        "reason_code": "Resolved payment failure; controller approved extension for additional reconciliation.",
    })
    features = extract_features(session)

    findings = R009LongSessionWithoutRejustificationRule().check(session, features)

    assert findings == []


def test_r010_flags_vendor_maintenance_and_payment_execution():
    session = make_session({"transaction_log": [{"tcode": "XK02"}, {"tcode": "F110"}]})
    features = extract_features(session)

    findings = R010SodConflictRule().check(session, features)

    assert len(findings) == 1
    assert findings[0].rule_id == "R-010"
    assert findings[0].severity == "critical"
    assert findings[0].location == "transaction_log"
    assert findings[0].evidence == "F110, XK02"


def test_r010_does_not_flag_payment_without_vendor_maintenance():
    session = make_session({"transaction_log": [{"tcode": "F110"}, {"tcode": "FBL1N"}]})
    features = extract_features(session)

    findings = R010SodConflictRule().check(session, features)

    assert findings == []


def test_rule_engine_runs_all_configured_rules():
    session = make_session({"reason_code": "fix", "os_command_log": [{"command": "whoami"}]})
    features = extract_features(session)

    findings = RuleEngine(rules=[R001WeakReasonRule(), R005OsCommandRule()]).run(session, features)

    assert {finding.rule_id for finding in findings} == {"R-001", "R-005"}
