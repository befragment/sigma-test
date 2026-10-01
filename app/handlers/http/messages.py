from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.domain.models import MessageStatus
from app.handlers.http.deps import Review
from app.handlers.http.schemas import MessageOut

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("", response_model=list[MessageOut], summary="Журнал обработки сообщений")
async def list_messages(
    review: Review,
    status: MessageStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    employee_id: int | None = None,
    shift_date: date | None = None,
) -> list[MessageOut]:
    messages = await review.list_messages(status, limit, offset, employee_id, shift_date)
    return [MessageOut.from_domain(m) for m in messages]
