from __future__ import annotations

from typing import Any

from sap_ff_reviewer.models import Finding, ReviewResult, SuggestedCorrection


def review_result_to_dict(result: ReviewResult) -> dict[str, Any]:
    return {
        "session_id": result.session_id,
        "verdict": result.verdict,
        "confidence": result.confidence,
        "findings": [finding_to_dict(finding) for finding in result.findings],
        "suggested_correction": correction_to_dict(result.suggested_correction),
        "diagnostics": result.diagnostics,
    }


def finding_to_dict(finding: Finding) -> dict[str, str]:
    return {
        "rule_id": finding.rule_id,
        "severity": finding.severity,
        "location": finding.location,
        "description": finding.description,
        "evidence": finding.evidence,
    }


def correction_to_dict(correction: SuggestedCorrection | None) -> dict[str, str | None] | None:
    if correction is None:
        return None

    return {
        "message_to_firefighter": correction.message_to_firefighter,
        "suggested_reason_rewrite": correction.suggested_reason_rewrite,
    }
