from __future__ import annotations

from pathlib import Path

from sap_ff_reviewer.correction import CorrectionBuilder
from sap_ff_reviewer.features import FeatureExtractor
from sap_ff_reviewer.models import ReviewResult, Session
from sap_ff_reviewer.parser import SessionParser
from sap_ff_reviewer.rules import RuleEngine, default_rules
from sap_ff_reviewer.verdict import VerdictAggregator


class ReviewEngine:
    def __init__(
        self,
        parser: SessionParser | None = None,
        feature_extractor: FeatureExtractor | None = None,
        rule_engine: RuleEngine | None = None,
        verdict_aggregator: VerdictAggregator | None = None,
        correction_builder: CorrectionBuilder | None = None,
        use_r002_llm: bool = False,
        ollama_model: str | None = None,
    ):
        self.parser = parser or SessionParser()
        self.feature_extractor = feature_extractor or FeatureExtractor()
        self.rule_engine = rule_engine or RuleEngine(rules=default_rules(use_r002_llm=use_r002_llm, ollama_model=ollama_model))
        self.verdict_aggregator = verdict_aggregator or VerdictAggregator()
        self.correction_builder = correction_builder or CorrectionBuilder()

    def review_file(self, path: str | Path) -> ReviewResult:
        session = self.parser.parse_file(path)
        return self.review_session(session)

    def review_session(self, session: Session) -> ReviewResult:
        features = self.feature_extractor.extract(session)
        findings = self.rule_engine.run(session, features)
        verdict = self.verdict_aggregator.aggregate(findings)
        confidence = self.verdict_aggregator.confidence(verdict, findings)
        correction = self.correction_builder.build(session, findings, verdict)
        diagnostics = self.rule_engine.diagnostics()

        return ReviewResult(
            session_id=session.session_id,
            verdict=verdict,
            confidence=confidence,
            findings=findings,
            suggested_correction=correction,
            diagnostics=diagnostics,
        )
