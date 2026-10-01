from fastapi import APIRouter, status

from app.handlers.http.deps import Directory
from app.handlers.http.schemas import EmployeeIn, EmployeeOut

router = APIRouter(prefix="/employees", tags=["employees"])


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def add_employee(body: EmployeeIn, directory: Directory) -> EmployeeOut:
    employee = await directory.add_employee(body.full_name, body.surname)
    return EmployeeOut.model_validate(employee)


@router.get("", response_model=list[EmployeeOut])
async def list_employees(directory: Directory) -> list[EmployeeOut]:
    return [EmployeeOut.model_validate(e) for e in await directory.list_employees()]
