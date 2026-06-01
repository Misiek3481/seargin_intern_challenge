from __future__ import annotations

from datetime import datetime, timedelta

from sap_ff_reviewer.models import Finding, Session, SessionFeatures


def _parse_log_timestamp(value: object, reference: datetime) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if timestamp.tzinfo is None and reference.tzinfo is not None:
        timestamp = timestamp.replace(tzinfo=reference.tzinfo)

    return timestamp


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


class R002ReasonActionMismatchRule(Rule):
    """
    Detect clear mismatches between the stated reason and performed actions.

    This is a deterministic heuristic, not a full semantic interpretation. It
    covers mismatch patterns visible in the historical data: read-only/check
    reasons with production changes, user-reset reasons with finance/vendor
    actions, FI posting reasons with MM invoice/goods movement actions, and
    reason codes that admit vendor maintenance plus payment execution.
    """

    rule_id = "R-002"
    severity = "high"
    READ_ONLY_REASON_TERMS = ("check", "investigation", "investigate", "display", "review")
    USER_RESET_REASON_TERMS = ("reset user", "user lock", "locked user", "hr consultant")
    FI_POSTING_REASON_TERMS = ("fi", "posting", "g/l", "gl account", "general ledger")
    VENDOR_REASON_TERMS = ("vendor", "bank details", "bank data", "iban")
    PAYMENT_REASON_TERMS = ("payment", "payment run", "f110")
    FINANCE_VENDOR_PAYMENT_TCODES = {"FB02", "F110", "F-53", "FBL1N", "XK02", "FK02", "XK05"}
    MM_TCODES = {"MIRO", "MIGO", "ME23N"}
    VENDOR_MAINTENANCE_TCODES = {"XK02", "FK02", "XK05"}
    PAYMENT_TCODES = {"F110", "F-53"}

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        reason = features.reason.lower()

        if self._contains_any(reason, self.READ_ONLY_REASON_TERMS) and features.change_count > 0:
            return [self._build_finding("Reason claims read-only investigation/check activity, but the session changed production data.", session.reason_code)]

        if self._contains_any(reason, self.USER_RESET_REASON_TERMS) and features.tcodes & self.FINANCE_VENDOR_PAYMENT_TCODES:
            evidence = f"reason={session.reason_code}; tcodes={', '.join(sorted(features.tcodes & self.FINANCE_VENDOR_PAYMENT_TCODES))}"
            return [self._build_finding("Reason indicates user reset activity, but transactions include finance/vendor/payment actions.", evidence)]

        if self._contains_any(reason, self.FI_POSTING_REASON_TERMS) and features.tcodes & self.MM_TCODES:
            evidence = f"reason={session.reason_code}; tcodes={', '.join(sorted(features.tcodes & self.MM_TCODES))}"
            return [self._build_finding("Reason indicates FI posting investigation, but transactions include MM purchasing/invoice actions.", evidence)]

        mentions_vendor_and_payment = self._contains_any(reason, self.VENDOR_REASON_TERMS) and self._contains_any(reason, self.PAYMENT_REASON_TERMS)
        has_vendor_and_payment = bool(features.tcodes & self.VENDOR_MAINTENANCE_TCODES) and bool(features.tcodes & self.PAYMENT_TCODES)
        if mentions_vendor_and_payment and has_vendor_and_payment:
            return [self._build_finding("Reason admits both vendor maintenance and payment execution in one firefighter session.", session.reason_code)]

        return []

    def _contains_any(self, text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    def _build_finding(self, description: str, evidence: str) -> Finding:
        return self.finding(
            location="reason_code",
            description=description,
            evidence=evidence,
        )


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


class R006ExcessiveChangeVolumeRule(Rule):
    rule_id = "R-006"
    severity = "high"
    MASS_CHANGE_THRESHOLD = 200
    SINGLE_OBJECT_CHANGE_THRESHOLD = 10
    SINGLE_OBJECT_TERMS = (
        "one vendor",
        "single vendor",
        "one user",
        "single user",
        "one customer",
        "single customer",
    )

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        if features.change_count >= self.MASS_CHANGE_THRESHOLD:
            return [
                self.finding(
                    location="change_log",
                    description="Change-document count exceeds the mass-change threshold for a firefighter session.",
                    evidence=f"change_count={features.change_count}; reason={session.reason_code}",
                )
            ]

        if self._reason_mentions_single_object(features.reason) and features.change_count > self.SINGLE_OBJECT_CHANGE_THRESHOLD:
            return [
                self.finding(
                    location="change_log",
                    description="Reason code indicates a single-object fix, but the session contains many change documents.",
                    evidence=f"change_count={features.change_count}; reason={session.reason_code}",
                )
            ]

        return []

    def _reason_mentions_single_object(self, reason: str) -> bool:
        normalized = reason.lower()
        return any(term in normalized for term in self.SINGLE_OBJECT_TERMS)


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


class R009LongSessionWithoutRejustificationRule(Rule):
    rule_id = "R-009"
    severity = "medium"
    AUTO_EXTEND_LIMIT_MINUTES = 120
    REJUSTIFICATION_TERMS = (
        "extended",
        "extension",
        "re-justified",
        "rejustified",
        "additional approval",
        "controller approved extension",
    )

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        if features.duration_minutes <= self.AUTO_EXTEND_LIMIT_MINUTES or self._reason_documents_extension(features.reason):
            return []

        return [
            self.finding(
                location="start_time/end_time",
                description="Session duration exceeds the auto-extend limit without documented re-justification.",
                evidence=f"duration_minutes={features.duration_minutes:.0f}; reason={session.reason_code}",
            )
        ]

    def _reason_documents_extension(self, reason: str) -> bool:
        normalized = reason.lower()
        return any(term in normalized for term in self.REJUSTIFICATION_TERMS)


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


class R011MissingTicketForProductionChangeRule(Rule):
    rule_id = "R-011"
    severity = "medium"

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        if features.has_ticket_reference:
            return []

        if features.change_count == 0:
            return [
                Finding(
                    rule_id=self.rule_id,
                    severity="low",
                    location="ticket_reference",
                    description="Firefighter session is missing a ticket reference for audit traceability.",
                    evidence="ticket_reference=<empty>; change_count=0",
                )
            ]

        return [
            self.finding(
                location="ticket_reference",
                description="Session made production data changes without a ticket reference for audit traceability.",
                evidence=f"ticket_reference=<empty>; change_count={features.change_count}",
            )
        ]


class R012LogOutsideFirefighterWindowRule(Rule):
    rule_id = "R-012"
    severity = "high"
    CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)
    LOG_FIELDS = (
        "transaction_log",
        "change_log",
        "system_log",
        "os_command_log",
    )

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        findings = []
        lower_bound = session.start_time - self.CLOCK_SKEW_TOLERANCE
        upper_bound = session.end_time + self.CLOCK_SKEW_TOLERANCE

        for log_name in self.LOG_FIELDS:
            entries = getattr(session, log_name)
            for index, entry in enumerate(entries):
                timestamp = _parse_log_timestamp(entry.get("timestamp"), session.start_time)
                if timestamp is None or lower_bound <= timestamp <= upper_bound:
                    continue

                findings.append(
                    self.finding(
                        location=f"{log_name}[{index}].timestamp",
                        description="Log entry timestamp falls outside the declared firefighter access window.",
                        evidence=(
                            f"timestamp={entry.get('timestamp')}; "
                            f"window={session.start_time.isoformat()}..{session.end_time.isoformat()}"
                        ),
                    )
                )

        return findings


class R013RepeatedAuthFailuresBeforeSensitiveChangeRule(Rule):
    rule_id = "R-013"
    severity = "high"
    MIN_AUTH_CHECKS = 2
    AUTH_CHECK_TCODE = "SU53"
    AUTH_FAILURE_MARKERS = (
        "authorization check",
        "authorization failed",
        "failed authorization",
        "not authorized",
        "no authorization",
        "missing authorization",
    )
    SENSITIVE_TABLES = {
        "T001",
        "LFA1",
        "LFB1",
        "LFBK",
        "USR02",
        "UST04",
        "USR12",
        "AGR_USERS",
        "AGR_1251",
        "AGR_DEFINE",
    }
    SENSITIVE_FIELDS = {
        "ACTVT",
        "AGR_NAME",
        "BANKL",
        "BANKN",
        "IBAN",
        "PROFILE",
        "SPERR",
        "UFLAG",
        "WAERS",
    }

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        auth_events = self._auth_check_events(session)
        if len(auth_events) < self.MIN_AUTH_CHECKS:
            return []

        threshold = auth_events[self.MIN_AUTH_CHECKS - 1]
        sensitive_changes = self._sensitive_changes_after(session, threshold)
        if not sensitive_changes:
            return []

        first_change = sensitive_changes[0]
        return [
            self.finding(
                location="transaction_log/change_log",
                description=(
                    "Repeated authorization-check reviews were followed by sensitive data changes; "
                    "this may indicate the firefighter did not have the required authorization before the later change."
                ),
                evidence=(
                    f"authorization_checks={len(auth_events)}; "
                    f"second_check={threshold.isoformat()}; "
                    f"sensitive_change={first_change}"
                ),
            )
        ]

    def _auth_check_events(self, session: Session) -> list[datetime]:
        events: list[datetime] = []

        for entry in session.transaction_log:
            timestamp = _parse_log_timestamp(entry.get("timestamp"), session.start_time)
            if timestamp is None:
                continue

            tcode = str(entry.get("tcode", "")).strip().upper()
            description = str(entry.get("description", "")).lower()
            if tcode == self.AUTH_CHECK_TCODE or any(marker in description for marker in self.AUTH_FAILURE_MARKERS):
                events.append(timestamp)

        for entry in session.system_log:
            timestamp = _parse_log_timestamp(entry.get("timestamp"), session.start_time)
            if timestamp is None:
                continue

            message = str(entry.get("message", "")).lower()
            if any(marker in message for marker in self.AUTH_FAILURE_MARKERS):
                events.append(timestamp)

        return sorted(events)

    def _sensitive_changes_after(self, session: Session, threshold: datetime) -> list[str]:
        changes: list[str] = []
        for entry in session.change_log:
            timestamp = _parse_log_timestamp(entry.get("timestamp"), session.start_time)
            if timestamp is None or timestamp <= threshold:
                continue

            table = str(entry.get("table", "")).strip().upper()
            field = str(entry.get("field", "")).strip().upper()
            if table in self.SENSITIVE_TABLES or field in self.SENSITIVE_FIELDS:
                changes.append(f"{table}.{field} at {timestamp.isoformat()}".strip("."))

        return changes


def default_rules() -> list[Rule]:
    return [
        R001WeakReasonRule(),
        R002ReasonActionMismatchRule(),
        R003DebugActivityRule(),
        R004DirectTableModificationRule(),
        R005OsCommandRule(),
        R006ExcessiveChangeVolumeRule(),
        R007AfterHoursWithoutEmergencyRule(),
        R008SelfApprovalRule(),
        R009LongSessionWithoutRejustificationRule(),
        R010SodConflictRule(),
        R011MissingTicketForProductionChangeRule(),
        R012LogOutsideFirefighterWindowRule(),
        R013RepeatedAuthFailuresBeforeSensitiveChangeRule(),
    ]


class RuleEngine:
    def __init__(self, rules: list[Rule] | None = None):
        self.rules = rules or default_rules()

    def run(self, session: Session, features: SessionFeatures) -> list[Finding]:
        findings = []
        for rule in self.rules:
            findings.extend(rule.check(session, features))
        return findings
