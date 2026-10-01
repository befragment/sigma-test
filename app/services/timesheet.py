from app.domain.errors import NotFound
from app.domain.models import Timesheet
from app.domain.ports import UnitOfWorkFactory
from app.domain.rules import build_timesheet, month_bounds, parse_month
from app.services.timesheet_xlsx import build_xlsx


class TimesheetService:
    """Табель за месяц: данные из хранилища → строки табеля → xlsx."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, month: str, chat_id: int | None = None) -> Timesheet:
        year, month_number = parse_month(month)
        start, end = month_bounds(year, month_number)
        async with self._uow_factory() as uow:
            group_title = None
            if chat_id is not None:
                groups = {group.chat_id: group for group in await uow.groups.list()}
                if chat_id not in groups:
                    raise NotFound(f"группа {chat_id} не зарегистрирована")
                group_title = groups[chat_id].title
            employees = await uow.employees.list()
            marks = await uow.attendance.list_between(start, end, chat_id)
        return build_timesheet(
            year,
            month_number,
            employees,
            marks,
            only_marked=chat_id is not None,
            group_title=group_title,
        )

    async def get_xlsx(self, month: str, chat_id: int | None = None) -> bytes:
        return build_xlsx(await self.get(month, chat_id))
