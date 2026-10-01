from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.handlers.http.deps import Timesheets

router = APIRouter(prefix="/timesheet", tags=["timesheet"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get(
    "",
    response_class=Response,
    responses={200: {"content": {XLSX: {}}, "description": "Табель в формате листа «Табель»"}},
    summary="Табель за месяц в xlsx",
)
async def get_timesheet(
    timesheets: Timesheets,
    month: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$", examples=["2025-09"])],
    chat_id: int | None = None,
) -> Response:
    content = await timesheets.get_xlsx(month, chat_id)
    # chat_id групп отрицательный: в имя файла идёт модуль, чтобы не было «--».
    filename = f"timesheet-{month}" + (f"-group{abs(chat_id)}" if chat_id is not None else "") + ".xlsx"
    return Response(
        content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
