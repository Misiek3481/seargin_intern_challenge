from __future__ import annotations

from sap_ff_reviewer.models import Finding, Session, SessionFeatures


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
        log_type = entry.get("type", "system_log")
        return f"{timestamp} - {message} ({log_type})"


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


def default_rules() -> list[Rule]:
    return [
        R001WeakReasonRule(),
        R003DebugActivityRule(),
        R005OsCommandRule(),
        R007AfterHoursWithoutEmergencyRule(),
        R008SelfApprovalRule(),
    ]


class RuleEngine:
    def __init__(self, rules: list[Rule] | None = None):
        self.rules = rules or default_rules()

    def run(self, session: Session, features: SessionFeatures) -> list[Finding]:
        findings = []
        for rule in self.rules:
            findings.extend(rule.check(session, features))
        return findings
