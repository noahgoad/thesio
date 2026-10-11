"""Process-local pause and honest read-only operational status."""
from collections import deque
from datetime import datetime, timezone
from secrets import token_urlsafe, compare_digest
from threading import Lock
from time import perf_counter
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool


class PauseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    paused: StrictBool


def install_operations(app, source_provider):
    mutex = Lock()
    paused = False
    active = errors = 0
    latencies = deque(maxlen=128)
    csrf = token_urlsafe(32)

    def operator_origin(request):
        if request.url.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise HTTPException(403, 'LOCAL_OPERATOR_ONLY')
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'OPERATOR_ORIGIN_DENIED')
        if origin:
            value = urlsplit(origin)
            if (value.scheme, value.netloc) != (request.url.scheme, request.url.netloc):
                raise HTTPException(403, 'OPERATOR_ORIGIN_DENIED')

    @app.get('/api/operator-token', include_in_schema=False)
    def operator_token(request: Request):
        operator_origin(request)
        return JSONResponse({'csrf_token': csrf}, headers={'Cache-Control': 'no-store'})

    @app.post('/api/pause')
    def set_pause(request: Request, body: PauseRequest):
        nonlocal paused
        operator_origin(request)
        supplied = request.headers.get('x-operator-token', '').encode('utf-8')
        if not compare_digest(supplied, csrf.encode('ascii')):
            raise HTTPException(403, 'OPERATOR_TOKEN_REQUIRED')
        with mutex:
            paused = body.paused
        return {'paused': body.paused, 'execution': 'NO_LIVE',
                'in_flight_policy': 'ALLOW_ACCEPTED_WORK_TO_FINISH'}

    @app.get('/readyz')
    def ready():
        reasons, ages = [], []
        try:
            for source in source_provider():
                stamp = source.get('available_at') or source.get('replay_cutoff')
                age = None
                if stamp:
                    try:
                        moment = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                        if moment.tzinfo is None:
                            raise ValueError('Missing timezone')
                        age = (datetime.now(timezone.utc) - moment).total_seconds()
                        if age < 0:
                            raise ValueError('Future source')
                    except (ValueError, TypeError, AttributeError):
                        age = None
                        reasons.append('SOURCE_CLOCK_INVALID')
                ages.append({'source_id': source.get('source_id'), 'age_seconds': age,
                             'status': source.get('status', 'REGISTERED'), 'current_quote': False})
            if not ages:
                reasons.append('NO_REGISTERED_SOURCES')
            elif all(row['status'] == 'UNAVAILABLE' for row in ages):
                reasons.append('SOURCES_UNAVAILABLE')
        except Exception:
            reasons.append('SOURCE_READINESS_UNAVAILABLE')
        with mutex:
            is_paused, current_active, total_errors = paused, active, errors
            times = sorted(latencies)
        if is_paused:
            reasons.append('OPERATOR_PAUSED')
        if total_errors:
            reasons.append('REQUEST_FAILURES_RECORDED')
        percentile = times[(95 * len(times) + 99) // 100 - 1] if times else None
        return JSONResponse({
            'ready': not reasons, 'paused': is_paused, 'mode': 'READ_ONLY',
            'execution': 'NO_LIVE', 'new_actions_allowed': not is_paused,
            'source_ages': ages, 'fresh_market_data': False,
            'active_requests': current_active, 'error_count': total_errors,
            'request_p95_ms': percentile, 'latency_sample_count': len(times),
            'degraded_reasons': sorted(set(reasons)), 'pause_scope': 'CURRENT_PROCESS',
            'queue_depth': None, 'queue_tracking': 'NO_MANAGED_WORKER_QUEUE',
        }, status_code=503 if reasons else 200, headers={'Cache-Control': 'no-store'})

    @app.middleware('http')
    async def gate(request: Request, call_next):
        nonlocal active, errors
        path = request.url.path
        work = (path.startswith('/api/') and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}
                and path not in {'/api/pause', '/api/export'}
                and not path.endswith(('/selection', '/decision', '/conclusion')))
        with mutex:
            blocked = paused and work
        if blocked:
            return JSONResponse({'detail': 'OPERATOR_PAUSED'}, status_code=503)
        measured = path.startswith('/api/') and path not in {'/api/pause', '/api/operator-token'}
        started = perf_counter()
        if measured:
            with mutex:
                active += 1
        failure = False
        try:
            response = await call_next(request)
            failure = response.status_code >= 400
            return response
        except Exception:
            failure = True
            raise
        finally:
            if measured:
                with mutex:
                    active -= 1
                    errors += int(failure)
                    latencies.append(round((perf_counter() - started) * 1000, 3))
