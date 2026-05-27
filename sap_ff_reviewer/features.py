from __future__ import annotations

from sap_ff_reviewer.models import Session, SessionFeatures


class FeatureExtractor:
    BUSINESS_HOURS_START = 8
    BUSINESS_HOURS_END = 18
    DEBUG_MARKERS = ("debug", "/h", "replace", "value changed")

    def extract(self, session: Session) -> SessionFeatures:
        reason = session.reason_code.strip()
        duration = session.end_time - session.start_time

        return SessionFeatures(
            reason=reason,
            reason_length=len(reason),
            has_ticket_reference=bool(session.ticket_reference.strip()),
            duration_minutes=duration.total_seconds() / 60,
            is_after_hours=self._is_after_hours(session),
            tcodes=self._extract_tcodes(session),
            transaction_count=len(session.transaction_log),
            changed_tables=self._extract_changed_tables(session),
            change_count=len(session.change_log),
            has_os_commands=bool(session.os_command_log),
            has_debug_activity=self._has_debug_activity(session),
            firefighter_is_requester=self._firefighter_is_requester(session),
        )

    def _is_after_hours(self, session: Session) -> bool:
        start_hour = session.start_time.hour
        return start_hour < self.BUSINESS_HOURS_START or start_hour >= self.BUSINESS_HOURS_END

    def _extract_tcodes(self, session: Session) -> set[str]:
        return {
            entry["tcode"].strip().upper()
            for entry in session.transaction_log
            if isinstance(entry.get("tcode"), str) and entry["tcode"].strip()
        }

    def _extract_changed_tables(self, session: Session) -> set[str]:
        return {
            entry["table"].strip().upper()
            for entry in session.change_log
            if isinstance(entry.get("table"), str) and entry["table"].strip()
        }

    def _has_debug_activity(self, session: Session) -> bool:
        for entry in session.system_log:
            message = str(entry.get("message", "")).lower()
            if any(marker in message for marker in self.DEBUG_MARKERS):
                return True
        return False

    def _firefighter_is_requester(self, session: Session) -> bool:
        if not session.ticket_requester:
            return False
        return session.firefighter_user.upper() == session.ticket_requester.upper()