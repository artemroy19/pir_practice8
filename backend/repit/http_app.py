import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .observability import REQUEST_ID, log

def error(status, detail):
    raise HTTPException(status, detail)


def app_for(title, db, schema):
    @asynccontextmanager
    async def lifespan(_):
        db.initialize(schema)
        yield

    app = FastAPI(title=title, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid(_, exc):
        fields = {}
        for issue in exc.errors():
            fields.setdefault(str(issue["loc"][-1]), []).append(issue["msg"])
        return JSONResponse(fields, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(_, exc):
        content = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
        return JSONResponse(jsonable_encoder(content), status_code=exc.status_code, headers=exc.headers)

    @app.middleware("http")
    async def correlate(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        identifier = incoming if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", incoming) else uuid4().hex
        marker = REQUEST_ID.set(identifier)
        started = time.monotonic()
        try:
            result = await call_next(request)
            result.headers["X-Request-ID"] = identifier
            log("http", method=request.method, path=request.url.path, status=result.status_code,
                duration_ms=round((time.monotonic() - started) * 1000))
            return result
        finally:
            REQUEST_ID.reset(marker)

    @app.get("/health/live")
    def live():
        return {"status": "ok", "service": db.name}

    @app.get("/health/ready")
    def ready():
        try:
            with db.connect() as session:
                session.one("SELECT 1 AS ok")
        except Exception:
            error(503, "База данных недоступна.")
        return {"status": "ready", "service": db.name}

    return app
