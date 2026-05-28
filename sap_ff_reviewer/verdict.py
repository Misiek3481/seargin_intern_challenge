from __future__ import annotations

from sap_ff_reviewer.models import Finding


class VerdictAggregator:
    REJECT_SEVERITIES = {"critical", "high"}

    def aggregate(self, findings: list[Finding]) -> str:
        if not findings:
            return "PASS"

        severities = {finding.severity for finding in findings}
        if severities & self.REJECT_SEVERITIES:
            return "REJECT"

        return "NEEDS_CORRECTION"

    def confidence(self, verdict: str, findings: list[Finding]) -> float:
        if verdict == "PASS":
            return 0.9

        severities = {finding.severity for finding in findings}
        if "critical" in severities:
            return 0.95
        if "high" in severities:
            return 0.85
        if "medium" in severities:
            return 0.75

        return 0.65
