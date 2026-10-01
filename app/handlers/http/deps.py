import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.services.directory import DirectoryService
from app.services.review import ReviewService


def require_admin(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = request.app.state.settings.admin_token
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing X-Admin-Token")


def _directory(request: Request) -> DirectoryService:
    return request.app.state.services.directory


def _review(request: Request) -> ReviewService:
    return request.app.state.services.review


Directory = Annotated[DirectoryService, Depends(_directory)]
Review = Annotated[ReviewService, Depends(_review)]
