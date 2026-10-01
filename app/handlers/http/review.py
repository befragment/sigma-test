from typing import Annotated

from fastapi import APIRouter, Query

from app.handlers.http.deps import Review
from app.handlers.http.schemas import ApproveIn, MessageOut

router = APIRouter(prefix="/review", tags=["review"])


@router.get("", response_model=list[MessageOut], summary="Сообщения на ручной проверке")
async def list_review(
    review: Review,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageOut]:
    return [MessageOut.from_domain(m) for m in await review.list_review(limit, offset)]


@router.post("/{id}/approve", response_model=MessageOut, summary="Подтвердить и поставить отметку")
async def approve(id: int, body: ApproveIn, review: Review) -> MessageOut:
    return MessageOut.from_domain(await review.approve(id, body.employee_id, body.shift_date))


@router.post("/{id}/reject", response_model=MessageOut, summary="Отклонить")
async def reject(id: int, review: Review) -> MessageOut:
    return MessageOut.from_domain(await review.reject(id))
