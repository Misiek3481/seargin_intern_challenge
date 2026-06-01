from __future__ import annotations

from sap_ff_reviewer.llm import OllamaR002Assessor, R002LlmAssessor
from sap_ff_reviewer.models import Finding, Session, SessionFeatures


# TODO: Implement remaining baseline rules from the challenge:
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


class R002ReasonActionMismatchRule(Rule):
    """
    Detect clear mismatches between the stated reason and performed actions.

    This is a deterministic heuristic, not a full semantic interpretation. It
    covers mismatch patterns visible in the historical data: read-only/check
    reasons with production changes, user-reset reasons with finance/vendor
    actions, and FI posting reasons with MM invoice/goods movement actions.
    Vendor/payment activity is treated as a risk signal for LLM confirmation,
    not as a deterministic R-002 mismatch when the reason already states it.
    """

    rule_id = "R-002"
    severity = "high"
    READ_ONLY_REASON_TERMS = ("check", "investigation", "investigate", "display", "review")
    USER_RESET_REASON_TERMS = ("reset user", "user lock", "locked user", "hr consultant")
    FI_POSTING_REASON_TERMS = ("fi", "posting", "g/l", "gl account", "general ledger")
    BASIS_REASON_TERMS = ("basis", "transport", "system maintenance", "system error", "work process", "runbook")
    FINANCE_VENDOR_PAYMENT_TCODES = {"FB02", "F110", "F-53", "FBL1N", "XK02", "FK02", "XK05"}
    MM_TCODES = {"MIRO", "MIGO", "ME23N"}
    VENDOR_MAINTENANCE_TCODES = {"XK02", "FK02", "XK05"}
    PAYMENT_TCODES = {"F110", "F-53"}
    BUSINESS_DATA_TCODES = FINANCE_VENDOR_PAYMENT_TCODES | MM_TCODES | {"SE16N", "SM30"}

    def __init__(self, llm_assessor: R002LlmAssessor | None = None):
        self.llm_assessor = llm_assessor
        self._llm_diagnostic: dict | None = None

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        heuristic_findings = self._check_heuristic(session, features)
        if heuristic_findings or self.llm_assessor is None:
            if heuristic_findings and self.llm_assessor is not None:
                self._llm_diagnostic = {
                    "status": "skipped_heuristic_hit",
                    "message": "Ollama was not called because the R-002 heuristic already produced a finding.",
                }
            else:
                self._llm_diagnostic = None
            return heuristic_findings

        should_call_llm, reason = self._should_call_llm(session, features)
        if not should_call_llm:
            self._llm_diagnostic = {
                "status": "skipped_prefilter",
                "message": f"Ollama was not called because the R-002 pre-filter did not find a likely scope mismatch: {reason}.",
            }
            return []

        assessment = self.llm_assessor.assess(session, features)
        self._llm_diagnostic = getattr(self.llm_assessor, "last_diagnostic", None)
        if assessment is None:
            return []

        return [
            self.finding(
                location="reason_code",
                description=assessment.description,
                evidence=assessment.evidence,
            )
        ]

    def diagnostics(self) -> dict:
        if self._llm_diagnostic is None:
            return {}
        return {"r002_llm": self._llm_diagnostic}

    def _check_heuristic(self, session: Session, features: SessionFeatures) -> list[Finding]:
        reason = features.reason.lower()

        if self._contains_any(reason, self.READ_ONLY_REASON_TERMS) and features.change_count > 0:
            return [self._build_finding("Reason claims read-only investigation/check activity, but the session changed production data.", session.reason_code)]

        if self._contains_any(reason, self.USER_RESET_REASON_TERMS) and features.tcodes & self.FINANCE_VENDOR_PAYMENT_TCODES:
            evidence = f"reason={session.reason_code}; tcodes={', '.join(sorted(features.tcodes & self.FINANCE_VENDOR_PAYMENT_TCODES))}"
            return [self._build_finding("Reason indicates user reset activity, but transactions include finance/vendor/payment actions.", evidence)]

        if self._contains_any(reason, self.FI_POSTING_REASON_TERMS) and features.tcodes & self.MM_TCODES:
            evidence = f"reason={session.reason_code}; tcodes={', '.join(sorted(features.tcodes & self.MM_TCODES))}"
            return [self._build_finding("Reason indicates FI posting investigation, but transactions include MM purchasing/invoice actions.", evidence)]

        return []

    def _should_call_llm(self, session: Session, features: SessionFeatures) -> tuple[bool, str]:
        reason = features.reason.lower()

        if self._contains_any(reason, self.USER_RESET_REASON_TERMS) and features.tcodes & self.FINANCE_VENDOR_PAYMENT_TCODES:
            return True, "user-support reason with finance/vendor/payment transactions"

        if self._contains_any(reason, self.READ_ONLY_REASON_TERMS) and features.change_count > 0:
            return True, "read-only reason with production changes"

        if self._contains_any(reason, self.FI_POSTING_REASON_TERMS) and features.tcodes & self.MM_TCODES:
            return True, "FI reason with MM transactions"

        if features.tcodes & self.PAYMENT_TCODES:
            return True, "payment execution transaction requires semantic R-002 confirmation"

        if self._contains_any(reason, self.BASIS_REASON_TERMS) and (features.tcodes & self.BUSINESS_DATA_TCODES or features.change_count > 0):
            return True, "technical/system reason with business data transactions or changes"

        if features.reason_length < 20 and (features.tcodes & self.BUSINESS_DATA_TCODES or features.change_count > 0):
            return True, "very short reason with business data transactions or changes"

        if self._has_multiple_business_scopes(features) and features.reason_length < 60:
            return True, "brief reason with multiple business scopes in actions"

        return False, "scope appears either clear enough for deterministic rules or too low-signal for R-002 LLM review"

    def _has_multiple_business_scopes(self, features: SessionFeatures) -> bool:
        scopes = 0
        if features.tcodes & (self.VENDOR_MAINTENANCE_TCODES | {"FBL1N"}):
            scopes += 1
        if features.tcodes & self.PAYMENT_TCODES:
            scopes += 1
        if features.tcodes & self.MM_TCODES:
            scopes += 1
        if features.changed_tables:
            scopes += 1
        return scopes >= 2

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

    This implementation recognizes vendor bank-data changes combined with a
    payment run in the same firefighter session. A generic vendor status update
    plus payment transaction is not enough evidence for this SoD conflict.
    """

    rule_id = "R-010"
    severity = "critical"
    VENDOR_MAINTENANCE_TCODES = {"XK02", "FK02", "XK05"}
    PAYMENT_RUN_TCODES = {"F110"}
    VENDOR_BANK_TABLES = {"LFBK"}
    VENDOR_BANK_FIELDS = {"BANKN", "IBAN", "BANKL"}

    def check(self, session: Session, features: SessionFeatures) -> list[Finding]:
        vendor_tcodes = features.tcodes & self.VENDOR_MAINTENANCE_TCODES
        payment_tcodes = features.tcodes & self.PAYMENT_RUN_TCODES
        bank_change_evidence = self._vendor_bank_change_evidence(session)

        if not payment_tcodes or not bank_change_evidence:
            return []

        evidence_items = sorted(vendor_tcodes | payment_tcodes)
        evidence_items.extend(bank_change_evidence)
        evidence = ", ".join(evidence_items)
        return [
            self.finding(
                location="transaction_log",
                description="SoD conflict: vendor bank-data change and payment run occurred in the same firefighter session.",
                evidence=evidence,
            )
        ]

    def _vendor_bank_change_evidence(self, session: Session) -> list[str]:
        evidence: list[str] = []
        for entry in session.change_log:
            table = str(entry.get("table", "")).strip().upper()
            field = str(entry.get("field", "")).strip().upper()
            if table in self.VENDOR_BANK_TABLES or field in self.VENDOR_BANK_FIELDS:
                evidence.append(f"{table}.{field}".strip("."))
        return evidence[:3]


def default_rules(
    use_r002_llm: bool = False,
    r002_llm_assessor: R002LlmAssessor | None = None,
    ollama_model: str | None = None,
) -> list[Rule]:
    if r002_llm_assessor is None and use_r002_llm:
        r002_llm_assessor = OllamaR002Assessor(model=ollama_model)

    return [
        R001WeakReasonRule(),
        R002ReasonActionMismatchRule(llm_assessor=r002_llm_assessor),
        R003DebugActivityRule(),
        R004DirectTableModificationRule(),
        R005OsCommandRule(),
        R006ExcessiveChangeVolumeRule(),
        R007AfterHoursWithoutEmergencyRule(),
        R008SelfApprovalRule(),
        R009LongSessionWithoutRejustificationRule(),
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

    def diagnostics(self) -> dict:
        diagnostics = {}
        for rule in self.rules:
            rule_diagnostics = getattr(rule, "diagnostics", None)
            if callable(rule_diagnostics):
                diagnostics.update(rule_diagnostics())
        return diagnostics
