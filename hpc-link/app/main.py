"""HPC Link - FastAPI Application Entry Point."""
from contextlib import asynccontextmanager
import asyncio
import structlog
from fastapi import FastAPI, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from asgi_correlation_id import CorrelationIdMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.config import get_settings
from app.security import auth_store, get_api_key, get_request_user, require_admin_user
from app.ssh_manager import ssh_manager
from app.routers import health, hpc, terminal, files, jobs, apps, auth, admin
from app.limiter import limiter

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars, # Add correlation ID from context
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Initialize Rate Limiter


def _upload_body_limit_for_path(settings, method: str, path: str) -> int | None:
    if method == "PUT" and path.startswith("/api/files/upload/"):
        return max(1, int(settings.upload_max_chunk_bytes))
    if method == "POST" and path.startswith("/api/apps/pi3/sessions/") and path.endswith("/images"):
        return max(1, int(settings.upload_pi3_max_body_bytes))
    if method == "POST" and path.startswith("/api/apps/marker/sessions/") and path.endswith("/documents"):
        return max(1, int(settings.upload_marker_max_body_bytes))
    if method == "POST" and path == "/api/apps/webhdp/components/test":
        return max(1, int(settings.webhdp_component_test_max_body_bytes))
    return None


class UploadBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        max_body = _upload_body_limit_for_path(
            settings,
            str(scope.get("method") or "").upper(),
            str(scope.get("path") or ""),
        )
        if max_body is None:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers") or []}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                body_size = int(content_length.decode("ascii"))
            except ValueError:
                body_size = 0
            if body_size > max_body:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (max {max_body} bytes)"},
                )
                await response(scope, receive, send)
                return

        body_parts: list[bytes] = []
        bytes_seen = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                await self.app(scope, receive, send)
                return
            body = message.get("body") or b""
            bytes_seen += len(body)
            if bytes_seen > max_body:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (max {max_body} bytes)"},
                )
                await response(scope, receive, send)
                return
            body_parts.append(body)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(body_parts), "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)


def _validate_startup_security() -> None:
    """Fail fast for insecure production configurations."""
    settings = get_settings()
    if settings.environment.strip().lower() not in {"prod", "production"}:
        return

    if settings.auth_token_secret.strip() == "change-me-in-production":
        raise RuntimeError("AUTH_TOKEN_SECRET must be set to a strong secret in production")
    if settings.admin_password.strip() == "change-me-admin-password":
        raise RuntimeError("ADMIN_PASSWORD must be set to a strong value in production")
    if settings.legacy_api_key_auth_enabled:
        raise RuntimeError("LEGACY_API_KEY_AUTH_ENABLED must be false in production")
    if "*" in settings.cors_origins:
        raise RuntimeError("CORS origins cannot include '*' in production")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    settings = get_settings()
    _validate_startup_security()
    auth_store.initialize()
    auth_store.ensure_admin_user(settings.admin_username, settings.admin_password)
    logger.info(
        "Starting HPC Link API",
        hpc_host=settings.hpc_host,
        hpc_user=settings.hpc_user
    )

    # Pre-connect to HPC on startup (optional, can be lazy)
    try:
        await asyncio.wait_for(ssh_manager.connect(), timeout=10)
        logger.info("Initial SSH connection established")
    except Exception as e:
        logger.warning("Initial SSH connection failed, will retry on first request", error=str(e))

    yield

    # Cleanup
    logger.info("Shutting down HPC Link API")
    await ssh_manager.disconnect()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description="Bridge between web applications and HPC resources",
        lifespan=lifespan,
    )

    # Rate Limiter State
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Middleware
    app.add_middleware(CorrelationIdMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(UploadBodyLimitMiddleware)

    @app.get("/metrics", dependencies=[Depends(get_api_key)])
    async def metrics(request: Request):
        """Prometheus metrics endpoint."""
        require_admin_user(get_request_user(request))
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # Public endpoints
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")

    # Protected endpoints
    app.include_router(hpc.router, prefix="/api", dependencies=[Depends(get_api_key)])
    app.include_router(files.router, prefix="/api", dependencies=[Depends(get_api_key)])
    app.include_router(apps.router, prefix="/api", dependencies=[Depends(get_api_key)])
    app.include_router(admin.router, prefix="/api")

    # Routers with mixed/custom auth (HTTP vs WebSocket)
    app.include_router(terminal.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")

    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "name": settings.api_title,
            "version": settings.api_version,
            "docs": "/docs",
            "health": "/health"
        }

    return app


# Create the app instance
app = create_app()
