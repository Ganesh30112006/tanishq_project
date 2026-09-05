from __future__ import annotations

import uuid

from fastapi import FastAPI, Request

from intelligence.ml_service.router import router as ml_router
from intelligence.nlp.router import router as nlp_router
from intelligence.ocr.router import router as ocr_router
from intelligence.rag.router import router as ai_router
from intelligence.report_service.router import router as report_router
from intelligence.settings import get_settings

app = FastAPI(
    title="CareSense AI - Intelligence Service",
    version="0.1.0",
    description=(
        "Computation and model inference only. This service makes no "
        "authorization decisions and has no database access."
    ),
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("x-correlation-id") or uuid.uuid4().hex
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = correlation_id
    return response


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": get_settings().service_name}


app.include_router(ml_router, prefix="/v1")
app.include_router(report_router, prefix="/v1")
app.include_router(nlp_router, prefix="/v1")
app.include_router(ocr_router, prefix="/v1")
app.include_router(ai_router, prefix="/v1")
