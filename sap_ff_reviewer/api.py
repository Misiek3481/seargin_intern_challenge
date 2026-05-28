from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sap_ff_reviewer.engine import ReviewEngine
from sap_ff_reviewer.models import InvalidSessionError
from sap_ff_reviewer.parser import SessionParser
from sap_ff_reviewer.serialization import review_result_to_dict


DECISIONS_FILE = Path("decisions.jsonl")
WEB_DIR = Path("web")

app = FastAPI(title="SAP Firefighter Log Compliance Reviewer")


class ControllerDecision(BaseModel):
    session_id: str
    decision: Literal["PASS", "REJECT", "SEND_BACK"]
    comment: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/review")
async def review_session(request: Request) -> dict:
    try:
        payload = await request.json()
        session = SessionParser().parse_dict(payload)
        result = ReviewEngine().review_session(session)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from exc
    except InvalidSessionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return review_result_to_dict(result)


@app.post("/decision")
def record_decision(decision: ControllerDecision) -> dict[str, str]:
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "session_id": decision.session_id,
        "decision": decision.decision,
        "comment": decision.comment,
    }

    with DECISIONS_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")

    return {"status": "recorded"}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True, check_dir=False), name="web")
