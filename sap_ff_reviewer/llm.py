from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from sap_ff_reviewer.models import Session, SessionFeatures


class R002LlmAssessor(Protocol):
    def assess(self, session: Session, features: SessionFeatures) -> "R002LlmAssessment | None":
        raise NotImplementedError


@dataclass(frozen=True)
class R002LlmAssessment:
    description: str
    evidence: str
    confidence: float


class OllamaR002Assessor:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 90.0,
    ):
        self.model = model or os.getenv("SAP_FF_OLLAMA_MODEL", "llama3.1")
        self.base_url = (base_url or os.getenv("SAP_FF_OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.last_diagnostic: dict | None = None

    def assess(self, session: Session, features: SessionFeatures) -> R002LlmAssessment | None:
        started_at = time.perf_counter()
        prompt = self._build_prompt(session, features)
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a SAP firefighter access compliance reviewer. "
                        "Return only compact JSON. Evaluate only R-002: a clear mismatch "
                        "between the stated reason scope and performed transactions or changes. "
                        "If your description or evidence says actions touched a materially different "
                        "business or technical scope than the reason, mismatch must be true."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0},
        }

        try:
            response = self._post_json(f"{self.base_url}/api/chat", payload)
            content = response.get("message", {}).get("content", "")
            parsed = self._parse_json_content(content)
        except TimeoutError as exc:
            self.last_diagnostic = self._diagnostic(
                status="timeout",
                message=f"Ollama did not respond within {self.timeout_seconds:.0f} seconds.",
                started_at=started_at,
                error=str(exc) or "timeout",
            )
            return None
        except urllib.error.URLError as exc:
            self.last_diagnostic = self._diagnostic(
                status="request_error",
                message="Ollama request failed before a valid response was received.",
                started_at=started_at,
                error=str(exc),
            )
            return None
        except json.JSONDecodeError as exc:
            self.last_diagnostic = self._diagnostic(
                status="invalid_json",
                message="Ollama responded, but the response was not valid JSON.",
                started_at=started_at,
                error=str(exc),
            )
            return None
        except (OSError, ValueError) as exc:
            self.last_diagnostic = self._diagnostic(
                status="error",
                message="Ollama response could not be used for R-002.",
                started_at=started_at,
                error=str(exc),
            )
            return None

        confidence = self._coerce_confidence(parsed.get("confidence"))
        description = str(parsed.get("description", "")).strip()
        evidence = str(parsed.get("evidence", "")).strip()
        mismatch = self._coerce_bool(parsed.get("mismatch"))

        if not mismatch:
            self.last_diagnostic = self._diagnostic(
                status="no_mismatch",
                message="Ollama responded and did not classify this as an R-002 mismatch.",
                started_at=started_at,
                mismatch=mismatch,
                confidence=confidence,
                description=description,
                evidence=evidence,
            )
            return None

        if confidence < 0.7:
            self.last_diagnostic = self._diagnostic(
                status="low_confidence",
                message="Ollama responded with mismatch=true, but confidence was below the 0.70 threshold.",
                started_at=started_at,
                mismatch=mismatch,
                confidence=confidence,
                description=description,
                evidence=evidence,
            )
            return None

        if not description or not evidence:
            self.last_diagnostic = self._diagnostic(
                status="incomplete_response",
                message="Ollama responded with mismatch=true, but description or evidence was missing.",
                started_at=started_at,
                mismatch=mismatch,
                confidence=confidence,
                description=description,
                evidence=evidence,
            )
            return None

        self.last_diagnostic = self._diagnostic(
            status="matched",
            message="Ollama responded and classified this as an R-002 mismatch.",
            started_at=started_at,
            mismatch=mismatch,
            confidence=confidence,
            description=description,
            evidence=evidence,
        )

        return R002LlmAssessment(
            description=f"LLM review found possible reason/action mismatch: {description}",
            evidence=f"{evidence} (model={self.model}, confidence={confidence:.2f})",
            confidence=confidence,
        )

    def _post_json(self, url: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _parse_json_content(self, content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        return json.loads(text)

    def _coerce_confidence(self, value: object) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))

    def _coerce_bool(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "1"}
        return bool(value)

    def _diagnostic(
        self,
        status: str,
        message: str,
        started_at: float,
        mismatch: bool | None = None,
        confidence: float | None = None,
        description: str | None = None,
        evidence: str | None = None,
        error: str | None = None,
    ) -> dict:
        return {
            "status": status,
            "message": message,
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
            "mismatch": mismatch,
            "confidence": confidence,
            "description": description,
            "evidence": evidence,
            "error": error,
        }

    def _build_prompt(self, session: Session, features: SessionFeatures) -> str:
        summary = {
            "rule": "R-002",
            "rule_definition": "Reason code mentions one system/module/scope, but transactions or changes touch a different one.",
            "session_id": session.session_id,
            "reason_code": session.reason_code,
            "ticket_reference": session.ticket_reference,
            "tcodes": sorted(features.tcodes),
            "transaction_log": session.transaction_log[:25],
            "changed_tables": sorted(features.changed_tables),
            "change_count": features.change_count,
            "change_log_sample": session.change_log[:25],
        }
        return (
            "Assess whether this session has an R-002 reason/action mismatch. "
            "Return mismatch=true when the reason says one scope but actions touch another, for example: "
            "user lock/reset/HR support reason with vendor, payment, FI, or accounting transactions; "
            "read-only/check/review reason with production changes; "
            "FI posting reason with MM invoice, purchasing, or goods movement transactions; "
            "Basis/transport/system-maintenance reason with business data changes. "
            "Return mismatch=false when the actions plausibly match the stated reason. "
            "Return exactly this JSON shape: "
            '{"mismatch": boolean, "confidence": number, "description": string, "evidence": string}.\n\n'
            f"{json.dumps(summary, ensure_ascii=False)}"
        )
