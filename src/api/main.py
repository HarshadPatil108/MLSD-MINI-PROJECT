"""FastAPI application entrypoint and ingestion boundary (F1, F2, D1)."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from src.api.quarantine import get_quarantine_store
from src.api.schemas import (
    AlertRequest,
    QuarantineErrorDetail,
    QuarantineErrorResponse,
    QuarantineListResponse,
    QuarantineRecord,
    RunResponse,
)
from src.rag.store import ManifestStore
from src.worker.queue import get_task_queue

logger = logging.getLogger(__name__)

app = FastAPI(
    title="IncidentOps Ingestion & Management API",
    description=(
        "Advisory Multi-Agent SRE Assistant Ingestion Boundary. "
        "Enforces strict Pydantic v2 data contracts, schema and cross-field validation, "
        "and quarantine isolation for malformed requests."
    ),
    version="0.1.0",
)


def _format_field_loc(loc: tuple[Any, ...]) -> str:
    """Format Pydantic error loc tuple into user-friendly dot path."""
    filtered = [str(part) for part in loc if part != "body"]
    if not filtered:
        return "body"
    return ".".join(filtered)


def _extract_payload_from_request_or_exc(exc: RequestValidationError) -> dict[str, Any]:
    """Safely extract raw payload dictionary from validation error."""
    raw_body = exc.body
    if isinstance(raw_body, dict):
        return raw_body
    if isinstance(raw_body, bytes):
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
            if isinstance(parsed, dict):
                return parsed
            return {"payload": parsed}
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return {"raw_bytes": raw_body.decode("utf-8", errors="replace")}
    if isinstance(raw_body, str):
        try:
            parsed = json.loads(raw_body)
            if isinstance(parsed, dict):
                return parsed
            return {"payload": parsed}
        except (json.JSONDecodeError, ValueError):
            return {"raw_text": raw_body}
    if raw_body is None:
        return {}
    return {"raw": str(raw_body)}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Intercept validation failures, store in quarantine, and return 422 with quarantine record ID."""
    raw_payload = _extract_payload_from_request_or_exc(exc)

    field_errors: list[QuarantineErrorDetail] = []
    for err in exc.errors():
        field_path = _format_field_loc(err.get("loc", ()))
        field_errors.append(
            QuarantineErrorDetail(
                field=field_path,
                message=err.get("msg", "Validation error"),
                type=err.get("type", "value_error"),
                input_value=err.get("input", None),
            )
        )

    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    client_info = f"{client_host} | {user_agent}"

    # Persist in SQLite quarantine store
    quarantine_store = get_quarantine_store()
    record = quarantine_store.record_quarantine(
        raw_payload=raw_payload,
        errors=field_errors,
        client_info=client_info,
        reason="Request failed validation contract",
    )

    logger.warning("Request quarantined [%s] with %d error(s)", record.id, len(field_errors))

    response_content = QuarantineErrorResponse(
        detail="Request validation failed. Payload has been quarantined.",
        quarantine_id=record.id,
        quarantined_at=record.quarantined_at,
        errors=field_errors,
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response_content.model_dump(mode="json"),
    )


@app.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an alert for multi-agent triage",
    description="Validates incoming alert contract. If valid, enqueues to task queue and returns run_id. If invalid, quarantines and returns 422.",
)
async def submit_run(alert: AlertRequest) -> RunResponse:
    """Ingest, validate, and enqueue an incident alert run."""
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    created_at = datetime.now(UTC)

    # Enqueue payload for async worker
    task_queue = get_task_queue()
    payload = alert.model_dump(mode="json")
    task_queue.enqueue(run_id=run_id, payload=payload)

    logger.info("Enqueued run [%s] for alert '%s'", run_id, alert.alert_name)

    return RunResponse(
        run_id=run_id,
        status="queued",
        created_at=created_at,
        alert_name=alert.alert_name,
        message="Alert validated successfully and enqueued for multi-agent triage.",
    )


@app.get(
    "/quarantine",
    response_model=QuarantineListResponse,
    summary="List quarantined requests",
    description="Retrieve paginated list of rejected malformed alert payloads.",
)
async def list_quarantine(
    limit: int = Query(default=100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Record offset"),
) -> QuarantineListResponse:
    """List quarantined records with pagination."""
    store = get_quarantine_store()
    records, total = store.list_records(limit=limit, offset=offset)
    return QuarantineListResponse(total=total, items=records)


@app.get(
    "/quarantine/{quarantine_id}",
    response_model=QuarantineRecord,
    summary="Get quarantined record by ID",
    description="Retrieve specific quarantined payload details and validation error diagnostics.",
)
async def get_quarantined_record(quarantine_id: str) -> QuarantineRecord:
    """Retrieve details of a single quarantined record."""
    store = get_quarantine_store()
    record = store.get_record(quarantine_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quarantine record '{quarantine_id}' not found.",
        )
    return record


@app.get(
    "/health",
    summary="Service health check",
    tags=["System"],
)
async def health_check() -> dict[str, Any]:
    """Check API service health and report corpus index status."""
    manifest = ManifestStore().load_manifest()
    index_status = "ready" if manifest.total_chunks > 0 else "empty"

    return {
        "status": "healthy",
        "service": "api",
        "index": {
            "status": index_status,
            "pg_version": manifest.pg_version,
            "total_chunks": manifest.total_chunks,
            "last_indexed_at": manifest.last_indexed_at.isoformat()
            if manifest.last_indexed_at
            else None,
            "build_duration_seconds": manifest.build_duration_seconds,
            "throughput_chunks_per_sec": manifest.throughput_chunks_per_sec,
        },
    }


@app.get(
    "/metrics",
    summary="Prometheus metrics",
    tags=["System"],
    response_class=PlainTextResponse,
)
async def prometheus_metrics() -> PlainTextResponse:
    """Expose Prometheus telemetry including corpus index size, duration, and throughput."""
    manifest = ManifestStore().load_manifest()
    metrics_lines = [
        "# HELP incidentops_index_chunks_total Total number of indexed chunks in the corpus.",
        "# TYPE incidentops_index_chunks_total gauge",
        f"incidentops_index_chunks_total {manifest.total_chunks}",
        "",
        "# HELP incidentops_index_build_duration_seconds Build duration of the last corpus index run in seconds.",
        "# TYPE incidentops_index_build_duration_seconds gauge",
        f"incidentops_index_build_duration_seconds {manifest.build_duration_seconds}",
        "",
        "# HELP incidentops_index_throughput_chunks_per_second Ingestion throughput in chunks per second.",
        "# TYPE incidentops_index_throughput_chunks_per_second gauge",
        f"incidentops_index_throughput_chunks_per_second {manifest.throughput_chunks_per_sec}",
        "",
    ]
    return PlainTextResponse(content="\n".join(metrics_lines))
