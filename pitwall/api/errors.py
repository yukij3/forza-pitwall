"""Uniform JSON errors: ``{"error": {"code": "...", "message": "..."}}``."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from pitwall.services.baselines import UnknownCategory
from pitwall.services.engine import AnalysisFailed, AnalysisUnavailable, BaselinesUnavailable
from pitwall.services.recorder import RecordingError
from pitwall.storage.db import NotFound

_HTTP_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
    503: "unavailable",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api")


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> Response:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, exc: NotFound) -> Response:
        return error_response(404, "not_found", f"{exc} not found")

    @app.exception_handler(RecordingError)
    async def _recording(request: Request, exc: RecordingError) -> Response:
        return error_response(409, exc.code, str(exc))

    @app.exception_handler(AnalysisUnavailable)
    async def _unavailable(request: Request, exc: AnalysisUnavailable) -> Response:
        return error_response(503, "analysis_unavailable", "The analysis engine is not available")

    @app.exception_handler(BaselinesUnavailable)
    async def _no_baselines(request: Request, exc: BaselinesUnavailable) -> Response:
        return error_response(503, "baselines_unavailable", "Baseline setups are not available")

    @app.exception_handler(UnknownCategory)
    async def _unknown_category(request: Request, exc: UnknownCategory) -> Response:
        return error_response(404, "not_found", f"{exc} not found")

    @app.exception_handler(AnalysisFailed)
    async def _failed(request: Request, exc: AnalysisFailed) -> Response:
        return error_response(500, "analysis_failed", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> Response:
        errors = exc.errors()
        if errors:
            first = errors[0]
            where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
            message = f"{where}: {first.get('msg', 'invalid')}" if where else first.get("msg", "")
        else:
            message = "Invalid request"
        return error_response(422, "validation_error", message)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        if not _is_api(request):
            return PlainTextResponse(str(exc.detail), status_code=exc.status_code)
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))
