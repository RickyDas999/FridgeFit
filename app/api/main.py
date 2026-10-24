import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import ingredients, inventory, meals, nutrition, recipes, recommendations
from app.api.session import SessionDep
from app.errors import InvalidInputError
from app.persistence.database import get_database_url, get_engine, get_session_factory

# The Vite dev server's origins, allowed when no deployed frontend origin is configured.
LOCAL_FRONTEND_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def get_frontend_origins() -> list[str]:
    """Return the browser origins allowed to call the API.

    Returns:
        Exactly ``FRONTEND_ORIGIN`` when it is set (production), otherwise the local Vite
        origins. A trailing slash is dropped, since browsers send origins without one.

    Raises:
        ValueError: If ``FRONTEND_ORIGIN`` is ``*``; the API never allows every origin.
    """
    origin = (os.environ.get("FRONTEND_ORIGIN") or "").strip().rstrip("/")
    if origin == "*":
        raise ValueError("FRONTEND_ORIGIN must be one exact origin, not '*'.")
    return [origin] if origin else LOCAL_FRONTEND_ORIGINS


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Release database connections when the application shuts down.

    Startup does not create or change tables: the schema comes from Alembic migrations
    (``alembic upgrade head``), run as a separate step before the API starts.

    Args:
        app: The application being started.

    Yields:
        Control back to FastAPI while the application serves requests.
    """
    yield
    app.state.engine.dispose()


async def handle_invalid_input(_request: Request, exc: InvalidInputError) -> JSONResponse:
    """Translate a domain validation failure into a 422 response.

    Args:
        _request: The request that failed; unused.
        exc: The validation error raised by domain or persistence code.

    Returns:
        A 422 JSON response whose ``detail`` is the error message.
    """
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def handle_request_validation(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return request validation errors as a 422 without echoing the rejected input.

    FastAPI's default handler includes each error's ``input``. That can be a value JSON cannot
    encode, such as Infinity (which Python's JSON parser accepts), turning a 422 into a 500.

    Args:
        _request: The request that failed; unused.
        exc: The validation error raised while parsing the request.

    Returns:
        A 422 JSON response whose ``detail`` lists each error's location, message, and type.
    """
    errors = [{k: v for k, v in error.items() if k != "input"} for error in exc.errors()]
    # A custom validator's ValueError sits in ``ctx``; encoded as-is it would become {}.
    detail = jsonable_encoder(errors, custom_encoder={Exception: str})
    return JSONResponse(status_code=422, content={"detail": detail})


def health(session: SessionDep) -> dict[str, str]:
    """Report that the API is running and can reach its database.

    Args:
        session: The request's database session.

    Returns:
        ``{"status": "ok"}``.
    """
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


def create_app(database_url: str | None = None) -> FastAPI:
    """Build the FridgeFit API application bound to one database.

    Args:
        database_url: SQLAlchemy connection string. Tests pass a temporary database; when
            omitted, ``get_database_url`` picks it from the environment.

    Returns:
        The configured FastAPI application.

    Raises:
        ValueError: If ``FRONTEND_ORIGIN`` is ``*``.
    """
    if database_url is None:
        database_url = get_database_url()
    app = FastAPI(title="FridgeFit", lifespan=lifespan)
    app.state.engine = get_engine(database_url)
    app.state.session_factory = get_session_factory(app.state.engine)
    # Lets the frontend call the API from another origin. No credentials: V1 has no auth.
    # Idempotency-Key is a custom header, so browsers preflight requests that send it.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_frontend_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
    app.add_exception_handler(InvalidInputError, handle_invalid_input)
    app.add_exception_handler(RequestValidationError, handle_request_validation)
    app.get("/health")(health)
    app.include_router(ingredients.router)
    app.include_router(inventory.router)
    app.include_router(recipes.router)
    app.include_router(nutrition.router)
    app.include_router(recommendations.router)
    app.include_router(meals.router)
    return app


app = create_app()
