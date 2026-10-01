"""Единственное место, где доменные исключения переводятся в HTTP-коды."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.errors import DomainError, InvalidState, NotFound, ValidationError

_STATUS_CODES: dict[type[DomainError], int] = {
    NotFound: status.HTTP_404_NOT_FOUND,
    InvalidState: status.HTTP_409_CONFLICT,
    ValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
    code = next(
        (code for cls, code in _STATUS_CODES.items() if isinstance(exc, cls)),
        status.HTTP_400_BAD_REQUEST,
    )
    return JSONResponse(status_code=code, content={"detail": str(exc)})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
