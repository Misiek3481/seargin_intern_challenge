from __future__ import annotations

from sap_ff_reviewer.models import Finding, Session, SuggestedCorrection


class DeterministicCorrectionBuilder:
    def build(self, session: Session, findings: list[Finding], verdict: str) -> SuggestedCorrection | None:
        if verdict != "NEEDS_CORRECTION":
            return None

        clarification_requests = self._clarification_requests(findings)
        message = self._build_message(session, clarification_requests)
        reason_rewrite = self._build_reason_rewrite(session, findings)

        return SuggestedCorrection(
            message_to_firefighter=message,
            suggested_reason_rewrite=reason_rewrite,
        )

    def _clarification_requests(self, findings: list[Finding]) -> list[str]:
        requests = []
        rule_ids = {finding.rule_id for finding in findings}

        if "R-001" in rule_ids:
            requests.append("provide a more specific reason code with affected process, object ID, root cause, and business impact")
        if "R-007" in rule_ids:
            requests.append("explain why emergency access was required outside business hours")

        for finding in findings:
            if finding.rule_id not in {"R-001", "R-007"}:
                requests.append(f"clarify finding {finding.rule_id}: {finding.description}")

        return requests or ["provide additional business context for the firefighter session"]

    def _build_message(self, session: Session, clarification_requests: list[str]) -> str:
        request_text = "; ".join(clarification_requests)
        return (
            f"Your firefighter session {session.session_id} requires additional information before it can be approved. "
            f"Please {request_text}."
        )

    def _build_reason_rewrite(self, session: Session, findings: list[Finding]) -> str | None:
        rule_ids = {finding.rule_id for finding in findings}
        if "R-001" not in rule_ids:
            return None

        ticket = session.ticket_reference or "<TICKET>"
        tcodes = ", ".join(self._session_tcodes(session)) or "<TCODES>"
        return (
            f"Resolved <specific production issue> for <affected object/company code> under {ticket}; "
            f"actions performed: {tcodes}; root cause: <root cause>; business impact: <impact>."
        )

    def _session_tcodes(self, session: Session) -> list[str]:
        tcodes = []
        for entry in session.transaction_log:
            tcode = entry.get("tcode")
            if isinstance(tcode, str) and tcode.strip():
                tcodes.append(tcode.strip().upper())
        return sorted(set(tcodes))


class LlmCorrectionBuilder:
    """TODO: generate correction text with an LLM while preserving rule findings as source of truth."""

    def build(self, session: Session, findings: list[Finding], verdict: str) -> SuggestedCorrection | None:
        raise NotImplementedError("LLM-based correction generation is not implemented yet.")


CorrectionBuilder = DeterministicCorrectionBuilder
