"""Offline-safe API boundary for the Narrative Research Desk."""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import JSONResponse

from narrative_research_desk.citations import verify_material_claims


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=128)
    cutoff: str = Field(min_length=20, max_length=40)
    mode: str = Field(pattern="^(FIXTURE|USER_SUPPLIED|PUBLIC_READ|HISTORICAL_BACKTEST|HISTORICAL_REPLAY|FORWARD_PAPER|USER_TEST)$")
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    question: str = Field(default="", max_length=4000)
    watchlist: list[str] = Field(default_factory=list, max_length=12)
    metric: str | None = Field(default=None, pattern='^(revenue|net_income|capex)$')
    operation: str | None = Field(default=None, pattern='^(level|change|compare)$')
    period_request: str | None = Field(default=None, pattern='^(annual|quarterly|latest)$')


class CompanyPrepareRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tickers: list[str] = Field(min_length=1, max_length=8)


class ConclusionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(default=2, ge=2, le=2, strict=True)
    decision_id: str = Field(min_length=1, max_length=128)
    verdict: str = Field(pattern='^(supports|challenges|insufficient)$')
    note: str = Field(default='', max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class SuggestionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=2_097_152)
    issuer_id: str = Field(pattern='^[A-Z0-9._-]{1,32}$')
    metric: str = Field(pattern='^(revenue|net_income|capex)$')


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narrative_id: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=1000)


class PositionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    issuer_id: str = Field(pattern='^[A-Z0-9._-]{1,32}$')
    weight: str | float

    @field_validator('weight', mode='before')
    @classmethod
    def reject_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError('WEIGHT_INVALID')
        return value


class BasketInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    narrative_id: str = Field(min_length=1, max_length=128)
    weights: dict[str, str | float] = Field(max_length=12)
    rationale: str = Field(default='', max_length=1000)
    invalidation_condition: str = Field(default='', max_length=1000)

    @field_validator('weights', mode='before')
    @classmethod
    def reject_boolean_weights(cls, values):
        if isinstance(values, dict) and any(isinstance(value, bool) for value in values.values()):
            raise ValueError('WEIGHT_INVALID')
        return values


class PortfolioInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    positions: list[PositionInput] = Field(max_length=100)
    baskets: list[BasketInput] = Field(min_length=2, max_length=2)


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stance: str = Field(pattern="^(support|challenge)$")
    quote: str = Field(min_length=1, max_length=8000)
    start: int | None = Field(default=None, ge=0, strict=True)
    issuer_id: str = Field(pattern="^[A-Z0-9._-]{1,32}$")


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1_000_000)
    origin: str = Field(min_length=1, max_length=1000)
    permission: str = Field(min_length=1, max_length=32)
    evidence: list[EvidenceInput] = Field(default_factory=list, max_length=30)


class FilingEvidenceInput(EvidenceInput):
    start: int | None = Field(default=None, ge=0, strict=True)


class FilingInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    raw_base64: str = Field(min_length=1, max_length=5_592_408)
    format: str = Field(pattern='^(html|text)$')
    issuer_id: str = Field(pattern='^[A-Z0-9._-]{1,32}$')
    cik: str = Field(min_length=1, max_length=10)
    accession: str = Field(min_length=20, max_length=20)
    origin: str = Field(min_length=1, max_length=1000)
    permission: str = Field(pattern='^(USER_OWNED|LICENSED)$')
    published_at: str | None = Field(default=None, max_length=40)
    evidence: list[FilingEvidenceInput] = Field(default_factory=list, max_length=30)


class RequestSizeLimitMiddleware:
    def __init__(self, app, max_bytes: int = 10 * 1024 * 1024):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            if int(headers.get(b"content-length", b"0")) > self.max_bytes:
                response = JSONResponse({"detail": "REQUEST_TOO_LARGE"}, status_code=413)
                await response(scope, receive, send)
                return
        except ValueError:
            response = JSONResponse({"detail": "CONTENT_LENGTH_INVALID"}, status_code=400)
            await response(scope, receive, send)
            return

        messages = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self.max_bytes:
                    response = JSONResponse({"detail": "REQUEST_TOO_LARGE"}, status_code=413)
                    await response(scope, receive, send)
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break

        cursor = 0

        async def replay():
            nonlocal cursor
            if cursor < len(messages):
                message = messages[cursor]
                cursor += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)


def create_app(service: Callable[[dict[str, Any]], dict[str, Any]] | Any, *, explanation_provider=None) -> FastAPI:
    app = FastAPI(title="Narrative Research Desk")
    from narrative_research_desk.operations import install_operations
    def operational_sources():
        rows = [{'source_id': name} for name in getattr(service, 'sources', {})]
        if getattr(service, 'sec', None):
            retained = service.sec.catalog()
            if retained:
                rows.append(retained)
        return rows
    install_operations(app, operational_sources)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=10 * 1024 * 1024)
    from narrative_research_desk.explanation import ExplanationService, ExplanationError, configured_nine_router, configured_limit
    explanations = ExplanationService(service, explanation_provider or configured_nine_router(),
        max_calls=configured_limit('C2_EXPLANATION_MAX_CALLS',20,100),
        max_concurrency=configured_limit('C2_EXPLANATION_MAX_CONCURRENCY',1,4))

    @app.post('/api/runs/{run_id}/explanation')
    def explain_run(run_id: str):
        try:
            return explanations.explain(run_id)
        except ExplanationError as error:
            raise HTTPException(status_code=error.status_code, detail=error.code) from None
        except Exception:
            raise HTTPException(status_code=503, detail='EXPLANATION_UNAVAILABLE') from None

    @app.get('/static/explanation.js')
    def explanation_js():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).parent/'static'/'explanation.js', media_type='text/javascript')

    @app.get("/", response_class=HTMLResponse)
    def workspace():
        page = Path(__file__).parent / "templates" / "index.html"
        if not page.is_file():
            raise HTTPException(status_code=503, detail="WORKSPACE_UNAVAILABLE")
        return HTMLResponse(page.read_text(encoding="utf-8"))

    @app.get("/static/workspace.css")
    def workspace_css():
        from fastapi.responses import FileResponse
        asset = Path(__file__).parent / "static" / "workspace.css"
        if not asset.is_file():
            raise HTTPException(status_code=503, detail="WORKSPACE_UNAVAILABLE")
        return FileResponse(asset, media_type="text/css")

    @app.get("/static/workspace.js")
    def workspace_js():
        from fastapi.responses import FileResponse
        asset = Path(__file__).parent / "static" / "workspace.js"
        if not asset.is_file():
            raise HTTPException(status_code=503, detail="WORKSPACE_UNAVAILABLE")
        return FileResponse(asset, media_type="text/javascript")

    @app.get("/static/product.css")
    def product_css():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).parent / "static" / "product.css", media_type="text/css")

    @app.get("/static/product.js")
    def product_js():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).parent / "static" / "product.js", media_type="text/javascript")

    @app.get("/static/saas.css")
    def saas_css():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).parent / "static" / "saas.css", media_type="text/css")

    @app.get("/static/thesio-logo.png")
    def brand_logo():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).parent / "static" / "thesio-logo.png", media_type="image/png")

    @app.get("/static/saas.js")
    def saas_js():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).parent / "static" / "saas.js", media_type="text/javascript")

    @app.get('/static/research-session.js')
    def research_session_js():
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).parent/'static'/'research-session.js',media_type='text/javascript')

    @app.post('/api/quote-suggestions')
    def quote_suggestions(body: SuggestionRequest):
        from narrative_research_desk.quote_suggestions import suggest_quotes
        return {'suggestions':suggest_quotes(body.text,issuer_id=body.issuer_id,metric=body.metric),
                'method':'LOCAL_KEYWORDS', 'stance':'NOT_ASSIGNED', 'issuer_attribution':'USER_MUST_CONFIRM'}

    if hasattr(service, 'conclude'):
        @app.post('/api/runs/{run_id}/conclusion')
        def conclude(run_id: str, body: ConclusionRequest):
            try:
                return service.conclude(run_id,body.model_dump())
            except Exception as error:
                raise HTTPException(status_code=getattr(error,'status_code',422),detail=getattr(error,'code',str(error))) from error

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "execution": "NO_LIVE"}

    @app.post("/api/analyze")
    def analyze(body: AnalyzeRequest):
        try:
            handler = getattr(service, "analyze", service if callable(service) else None)
            if handler is None:
                raise ValueError("RESEARCH_SERVICE_UNAVAILABLE")
            result = handler(body.model_dump())
            if not isinstance(result, dict):
                raise ValueError("RESEARCH_RESULT_INVALID")
            citation_sources = result.get("_citation_sources", result.get("sources"))
            material_claims = result.get("_material_claims", result.get("material_claims"))
            fact_ids = result.get("_fact_ids", result.get("fact_ids"))
            if material_claims is not None:
                if not isinstance(material_claims, list) or not isinstance(citation_sources, dict) or not isinstance(fact_ids, list):
                    raise ValueError("RESEARCH_EVIDENCE_INVALID")
                result = dict(result)
                result.pop("_citation_sources", None)
                result.pop("_material_claims", None)
                result.pop("_fact_ids", None)
                result.pop("sources", None)
                result.pop("material_claims", None)
                result.pop("fact_ids", None)
                verify_material_claims(material_claims, citation_sources, set(fact_ids))
            return result
        except Exception as error:
            status_code = getattr(error, "status_code", 422 if isinstance(error, ValueError) else 503)
            detail = getattr(error, "code", str(error))
            raise HTTPException(status_code=status_code, detail=detail) from error

    @app.get("/api/capabilities")
    def capabilities():
        return {"synthetic_example_available": "fixture-ai-capex-001" in getattr(service, "sources", {}),
                "supplied_text_available": hasattr(service, "ingest"), "web_search": False,
                "filing_import_available": hasattr(service, 'ingest_filing'),
                "retained_sec": service.sec.catalog() if getattr(service, 'sec', None) else None,
                "company_directory": bool(getattr(service, 'company_directory', None))}

    @app.get('/api/companies')
    def companies(q: str = ''):
        directory = getattr(service, 'company_directory', None)
        try:
            if directory is None:
                raise HTTPException(status_code=503, detail='COMPANY_DIRECTORY_NOT_CONFIGURED')
            return directory.search(q)
        except Exception as error:
            return JSONResponse(status_code=getattr(error, 'status_code', 422 if isinstance(error, ValueError) else 503),
                                content={'companies': [], 'total': 0, 'error': getattr(error, 'detail', str(error))})

    @app.post('/api/companies/prepare')
    def prepare_companies(body: CompanyPrepareRequest):
        directory = getattr(service, 'company_directory', None)
        try:
            if directory is None:
                raise HTTPException(status_code=503, detail='COMPANY_DIRECTORY_NOT_CONFIGURED')
            return directory.prepare(body.tickers)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=getattr(error, 'status_code', 422 if isinstance(error, ValueError) else 503),
                                detail=str(error)) from error

    if hasattr(service, 'ingest_filing'):
        @app.post('/api/filings/preview')
        def preview_filing(body: FilingInput):
            from narrative_research_desk.filings import preview_filing as extract
            try:
                return extract(body.model_dump())
            except ValueError as error:
                raise HTTPException(status_code=getattr(error, 'status_code', 422), detail=str(error)) from error

        @app.post('/api/filings', status_code=201)
        def ingest_filing(body: FilingInput):
            try:
                return service.ingest_filing(body.model_dump())
            except ValueError as error:
                raise HTTPException(status_code=getattr(error, 'status_code', 422), detail=str(error)) from error

    if hasattr(service, 'portfolio'):
        @app.post('/api/runs/{run_id}/portfolio', status_code=201)
        def portfolio(run_id: str, body: PortfolioInput):
            try:
                return service.portfolio(run_id, body.model_dump())
            except Exception as error:
                raise HTTPException(status_code=getattr(error, 'status_code', 422 if isinstance(error, ValueError) else 503), detail=getattr(error, 'code', str(error))) from error

    if hasattr(service, "ingest"):
        @app.post("/api/sources", status_code=201)
        def ingest(body: SourceInput):
            try:
                return service.ingest(body.model_dump())
            except Exception as error:
                raise HTTPException(status_code=getattr(error, "status_code", 422 if isinstance(error, ValueError) else 503), detail=getattr(error, "code", str(error))) from error

    if hasattr(service, "read"):
        @app.get("/api/runs/{run_id}")
        def read_run(run_id: str):
            try:
                return service.read(run_id)
            except Exception as error:
                raise HTTPException(status_code=getattr(error, "status_code", 422 if isinstance(error, ValueError) else 503), detail=getattr(error, "code", str(error))) from error

    if hasattr(service, "choose"):
        @app.post("/api/runs/{run_id}/decision")
        def choose(run_id: str, body: DecisionRequest):
            try:
                return service.choose(run_id, body.model_dump())
            except Exception as error:
                raise HTTPException(status_code=getattr(error, "status_code", 422 if isinstance(error, ValueError) else 503), detail=getattr(error, "code", str(error))) from error

    if hasattr(service, "export"):
        @app.get("/api/runs/{run_id}/export")
        def export(run_id: str, format: str = 'json'):
            try:
                if format not in {'json', 'md'}:
                    raise ValueError('EXPORT_FORMAT_INVALID')
                artifact = service.export(run_id) if format == 'json' else service.export(run_id, format=format)
                return Response(content=artifact["content"], media_type=artifact["mime"], headers={"X-Content-SHA256": artifact["sha256"]})
            except Exception as error:
                raise HTTPException(status_code=getattr(error, "status_code", 422 if isinstance(error, ValueError) else 503), detail=getattr(error, "code", str(error))) from error

    return app
