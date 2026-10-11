from typing import Annotated, Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session


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
