from __future__ import annotations

import json
import os
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
        timeout_seconds: float = 12.0,
    ):
        self.model = model or os.getenv("SAP_FF_OLLAMA_MODEL", "llama3.1")
        self.base_url = (base_url or os.getenv("SAP_FF_OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.timeout_seconds = timeout_seconds

    def assess(self, session: Session, features: SessionFeatures) -> R002LlmAssessment | None:
        prompt = self._build_prompt(session, features)
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a SAP firefighter access compliance reviewer. "
                        "Return only compact JSON. Flag R-002 only for a clear mismatch "
                        "between the stated reason and the performed transactions or changes."
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
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, ValueError):
            return None

        if not parsed.get("mismatch"):
            return None

        confidence = self._coerce_confidence(parsed.get("confidence"))
        if confidence < 0.7:
            return None

        description = str(parsed.get("description", "")).strip()
        evidence = str(parsed.get("evidence", "")).strip()
        if not description or not evidence:
            return None

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
            "Be conservative: return mismatch=false when the actions plausibly match the reason. "
            "Return exactly this JSON shape: "
            '{"mismatch": boolean, "confidence": number, "description": string, "evidence": string}.\n\n'
            f"{json.dumps(summary, ensure_ascii=False)}"
        )
