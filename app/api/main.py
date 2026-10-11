from contextlib import asynccontextmanager
from typing import Annotated, Iterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import InvalidInputError
from app.persistence.database import DATABASE_URL, Base, get_engine, get_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create any missing tables at startup and release database connections at shutdown.

    This bootstraps a fresh SQLite database for V1. It only creates missing tables and never
    alters existing ones, so it is not a substitute for migrations (Alembic is deferred).

    Args:
        app: The application being started.

    Yields:
        Control back to FastAPI while the application serves requests.
    """
    Base.metadata.create_all(app.state.engine)
    yield
    app.state.engine.dispose()


def get_session(request: Request) -> Iterator[Session]:
    """Provide one database session for the duration of a single request.

    The session is closed when the request ends. Anything not committed by then is discarded,
    so a request that fails partway through writes nothing.

    Args:
        request: The incoming request, used to reach the app's session factory.

    Yields:
        An open SQLAlchemy Session.
    """
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


async def handle_invalid_input(_request: Request, exc: InvalidInputError) -> JSONResponse:
    """Translate a domain validation failure into a 422 response.

    Args:
        _request: The request that failed; unused.
        exc: The validation error raised by domain or persistence code.

    Returns:
        A 422 JSON response whose ``detail`` is the error message.
    """
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def health(session: SessionDep) -> dict[str, str]:
    """Report that the API is running and can reach its database.

    Args:
        session: The request's database session.

    Returns:
        ``{"status": "ok"}``.
    """
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


def create_app(database_url: str = DATABASE_URL) -> FastAPI:
    """Build the FridgeFit API application bound to one database.

    Args:
        database_url: SQLAlchemy connection string. Tests pass a temporary database.

    Returns:
        The configured FastAPI application.
    """
    app = FastAPI(title="FridgeFit", lifespan=lifespan)
    app.state.engine = get_engine(database_url)
    app.state.session_factory = get_session_factory(app.state.engine)
    app.add_exception_handler(InvalidInputError, handle_invalid_input)
    app.get("/health")(health)
    return app


app = create_app()
