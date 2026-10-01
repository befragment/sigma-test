from fastapi import Depends, FastAPI

from app.handlers.http import bindings, employees, groups, health, messages, review, timesheet
from app.handlers.http.deps import require_admin
from app.handlers.http.errors import register_exception_handlers


def register_http(app: FastAPI) -> None:
    app.include_router(health.router)
    for module in (groups, employees, bindings, messages, review, timesheet):
        app.include_router(module.router, dependencies=[Depends(require_admin)])
    register_exception_handlers(app)
