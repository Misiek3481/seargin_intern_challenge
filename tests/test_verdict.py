from sap_ff_reviewer.models import Finding
from sap_ff_reviewer.verdict import VerdictAggregator


def make_finding(severity):
    return Finding(
        rule_id="R-TEST",
        severity=severity,
        location="reason_code",
        description="Test finding.",
        evidence="test evidence",
    )


def test_returns_pass_when_there_are_no_findings():
    assert VerdictAggregator().aggregate([]) == "PASS"


def test_returns_reject_for_critical_findings():
    findings = [make_finding("critical")]

    assert VerdictAggregator().aggregate(findings) == "REJECT"


def test_returns_reject_for_high_findings():
    findings = [make_finding("high")]

    assert VerdictAggregator().aggregate(findings) == "REJECT"


def test_returns_needs_correction_for_medium_or_low_findings():
    findings = [make_finding("medium"), make_finding("low")]

    assert VerdictAggregator().aggregate(findings) == "NEEDS_CORRECTION"


def test_confidence_reflects_strongest_severity():
    aggregator = VerdictAggregator()

    assert aggregator.confidence("PASS", []) == 0.9
    assert aggregator.confidence("REJECT", [make_finding("critical")]) == 0.95
    assert aggregator.confidence("REJECT", [make_finding("high")]) == 0.85
    assert aggregator.confidence("NEEDS_CORRECTION", [make_finding("medium")]) == 0.75
    assert aggregator.confidence("NEEDS_CORRECTION", [make_finding("low")]) == 0.65
