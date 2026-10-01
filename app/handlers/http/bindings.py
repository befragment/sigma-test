from fastapi import APIRouter

from app.handlers.http.deps import Directory
from app.handlers.http.schemas import BindingIn, BindingOut

router = APIRouter(prefix="/bindings", tags=["bindings"])


@router.put("/{tg_user_id}", response_model=BindingOut, summary="Привязать Telegram-аккаунт к сотруднику")
async def bind(tg_user_id: int, body: BindingIn, directory: Directory) -> BindingOut:
    return BindingOut.model_validate(await directory.bind(tg_user_id, body.employee_id))
