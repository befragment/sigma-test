from fastapi import APIRouter

from app.handlers.http.deps import Directory
from app.handlers.http.schemas import GroupIn, GroupOut

router = APIRouter(prefix="/groups", tags=["groups"])


@router.post("", response_model=GroupOut, summary="Создать или обновить группу")
async def upsert_group(body: GroupIn, directory: Directory) -> GroupOut:
    group = await directory.upsert_group(**body.model_dump())
    return GroupOut.model_validate(group)


@router.get("", response_model=list[GroupOut])
async def list_groups(directory: Directory) -> list[GroupOut]:
    return [GroupOut.model_validate(group) for group in await directory.list_groups()]
