from __future__ import annotations

from sap_ff_reviewer.models import Finding, Session, SessionFeatures


# TODO: Implement remaining baseline rules from the challenge:
# - R-002: Reason mentions one system/module, but transactions touch a different one.
# - R-006: Transaction or change count exceeds a reasonable threshold for the stated reason.
# - R-009: Session duration exceeds the auto-extend limit without re-justification.
#
# TODO: Consider additional rules after reviewing train/test patterns:
# - R-011: Missing ticket reference for a session that made production changes.
# - R-012: Sensitive table changes, e.g. vendor bank, company code, user master, or role tables.
# - R-013: Display-only reason but write/change transactions or change_log entries are present.
# - R-014: Logs outside the declared firefighter time window.
# - R-015: Repeated failed authorization checks followed by sensitive changes.
# - R-016: Suspicious transaction sequence, e.g. table inspection immediately followed by direct edit.


class Rule:
    rule_id: str
    severity: str

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        raise NotImplementedError

    def finding(self, location: str, description: str, evidence: str) -> Finding:
        return Finding(
            rule_id=self.rule_id,
            severity=self.severity,
            location=location,
            description=description,
            evidence=evidence,
        )


class R001WeakReasonRule(Rule):
    rule_id = "R-001"
    severity = "medium"
    GENERIC_REASONS = {"test", "fix", "asap", "urgent", "issue", "production issue", "prod issue"}

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        reason = features.reason.lower()
        is_too_short = features.reason_length < 20
        is_generic = reason in self.GENERIC_REASONS

        if not features.reason or is_too_short or is_generic:
            return [
                self.finding(
                    location="reason_code",
                    description="Reason code is missing, too short, or too generic for firefighter access review.",
                    evidence=session.reason_code,
                )
            ]

        return []


class R003DebugActivityRule(Rule):
    rule_id = "R-003"
    severity = "critical"
    DEBUG_MARKERS = ("debug", "/h", "replace", "value changed")

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        findings = []

        for index, entry in enumerate(session.system_log):
            message = str(entry.get("message", ""))
            if self._is_debug_message(message):
                findings.append(
                    self.finding(
                        location=f"system_log[{index}]",
                        description="Debug-related activity was recorded during the firefighter session.",
                        evidence=self._format_system_log_entry(entry),
                    )
                )

        return findings

    def _is_debug_message(self, message: str) -> bool:
        normalized = message.lower()
        return any(marker in normalized for marker in self.DEBUG_MARKERS)

    def _format_system_log_entry(self, entry: dict) -> str:
        timestamp = entry.get("timestamp", "<missing timestamp>")
        message = entry.get("message", "<missing message>")
        log_type = entry.get("type", "<missing system_log type>")
        return f"{timestamp} - {message} ({log_type})"


class R004DirectTableModificationRule(Rule):
    rule_id = "R-004"
    severity = "high"
    DIRECT_TABLE_TCODES = {"SE16N", "SM30"}
    SENSITIVE_TABLES = {"T001", "LFA1", "LFB1", "LFBK", "USR02"}
    # TODO: Expand these terms from historical reviews, ticketing metadata, or client-specific data-fix wording.
    DATA_FIX_TERMS = (
        "data fix",
        "approved data fix",
        "approved change",
        "change request",
        "table correction",
        "production data correction",
    )

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        direct_table_tcodes = features.tcodes & self.DIRECT_TABLE_TCODES
        if not direct_table_tcodes:
            return []

        sensitive_tables = features.changed_tables & self.SENSITIVE_TABLES
        if not sensitive_tables or self._reason_documents_data_fix(session.reason_code):
            return []

        return [
            self.finding(
                location="change_log",
                description="Direct table maintenance changed sensitive table data without reason code documenting an approved data fix.",
                evidence=f"tcodes={', '.join(sorted(direct_table_tcodes))}; tables={', '.join(sorted(sensitive_tables))}",
            )
        ]

    def _reason_documents_data_fix(self, reason_code: str) -> bool:
        normalized = reason_code.lower()
        return any(term in normalized for term in self.DATA_FIX_TERMS)


class R005OsCommandRule(Rule):
    rule_id = "R-005"
    severity = "critical"

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        findings = []

        for index, entry in enumerate(session.os_command_log):
            command = entry.get("command", "<missing command>")
            parameters = entry.get("parameters", "")
            findings.append(
                self.finding(
                    location=f"os_command_log[{index}]",
                    description="OS-level command execution was recorded during the firefighter session.",
                    evidence=f"{command} {parameters}".strip(),
                )
            )

        return findings


class R007AfterHoursWithoutEmergencyRule(Rule):
    rule_id = "R-007"
    severity = "medium"
    EMERGENCY_TERMS = ("urgent", "emergency", "production down", "outage", "failed", "failure", "incident", "inc")

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        if not features.is_after_hours or self._reason_indicates_emergency(features.reason):
            return []

        return [
            self.finding(
                location="start_time",
                description="Session occurred outside business hours without a clear emergency justification.",
                evidence=session.start_time.isoformat(),
            )
        ]

    def _reason_indicates_emergency(self, reason: str) -> bool:
        normalized = reason.lower()
        return any(term in normalized for term in self.EMERGENCY_TERMS)


class R008SelfApprovalRule(Rule):
    rule_id = "R-008"
    severity = "high"

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        if not features.firefighter_is_requester:
            return []

        return [
            self.finding(
                location="ticket_requester",
                description="Firefighter user and ticket requester are the same person.",
                evidence=f"firefighter_user={session.firefighter_user}, ticket_requester={session.ticket_requester}",
            )
        ]


class R010SodConflictRule(Rule):
    """
    Detect the only SoD conflict currently modeled from historical data.

    This implementation recognizes vendor maintenance transactions combined with
    payment execution transactions in the same firefighter session. No other SoD
    pairs are currently modeled because this was the only clear conflict pattern
    observed in the provided historical dataset, and the available transaction
    mix does not provide enough evidence for reliable additional SoD pairs.
    """

    rule_id = "R-010"
    severity = "critical"
    VENDOR_MAINTENANCE_TCODES = {"XK02", "FK02", "XK05"}
    PAYMENT_TCODES = {"F110", "F-53"}

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        vendor_tcodes = features.tcodes & self.VENDOR_MAINTENANCE_TCODES
        payment_tcodes = features.tcodes & self.PAYMENT_TCODES

        if not vendor_tcodes or not payment_tcodes:
            return []

        evidence = ", ".join(sorted(vendor_tcodes | payment_tcodes))
        return [
            self.finding(
                location="transaction_log",
                description="SoD conflict: vendor maintenance and payment execution occurred in the same firefighter session.",
                evidence=evidence,
            )
        ]


def default_rules() -> list[Rule]:
    return [
        R001WeakReasonRule(),
        R003DebugActivityRule(),
        R004DirectTableModificationRule(),
        R005OsCommandRule(),
        R007AfterHoursWithoutEmergencyRule(),
        R008SelfApprovalRule(),
        R010SodConflictRule(),
    ]


class RuleEngine:
    def __init__(self, rules: list[Rule] | None = None):
        self.rules = rules or default_rules()

    def run(self, session: Session, features: SessionFeatures) -> list[Finding]:
        findings = []
        for rule in self.rules:
            findings.extend(rule.check(session, features))
        return findings
