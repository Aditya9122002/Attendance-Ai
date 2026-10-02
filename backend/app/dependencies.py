"""Shared FastAPI dependencies: database session and the current school.

Purpose: give route functions a database session and the school they act for.
Input: the incoming request.
Output: an AsyncSession per request, and the school's UUID.
Dependencies: the session factory that main.py stores on app.state at startup.

WARNING: get_current_school_id trusts an X-School-Id header. That is a development
stand-in with NO authentication. It must be replaced by real authentication (a verified
token that carries the school) before any real school or real data touches this API.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one database session per request and always close it."""
    async with request.app.state.session_factory() as session:
        yield session


async def get_current_school_id(
    x_school_id: Annotated[uuid.UUID | None, Header()] = None,
) -> uuid.UUID:
    """Development stand-in for authentication. See the module warning."""
    if x_school_id is None:
        raise HTTPException(status_code=401, detail="Missing X-School-Id header")
    return x_school_id


DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentSchoolId = Annotated[uuid.UUID, Depends(get_current_school_id)]
