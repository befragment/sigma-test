from datetime import time

import pytest

from app.domain.errors import NotFound, ValidationError
from app.domain.models import Binding
from app.services.directory import DirectoryService
from tests.fakes import FakeDB


@pytest.fixture
def db() -> FakeDB:
    return FakeDB()


@pytest.fixture
def service(db: FakeDB) -> DirectoryService:
    return DirectoryService(db.uow)


async def test_add_employee_normalizes_name_and_surname(db, service):
    employee = await service.add_employee("  Ёлкин   Олег ")

    assert (employee.full_name, employee.surname_norm) == ("Ёлкин Олег", "елкин")
    assert db.state.employees[employee.id] == employee


async def test_add_employee_with_explicit_surname(service):
    employee = await service.add_employee("Олег Ёлкин", surname="Ёлкин")
    assert employee.surname_norm == "елкин"


@pytest.mark.parametrize("full_name", ["", "   ", "123 !!"])
async def test_add_employee_rejects_names_without_letters(db, service, full_name):
    with pytest.raises(ValidationError):
        await service.add_employee(full_name)
    assert db.state.employees == {}


async def test_upsert_group_validates_window(db, service):
    with pytest.raises(ValidationError):
        await service.upsert_group(-1, "g", time(8, 0), time(8, 0))
    assert db.state.groups == {}


async def test_bind_unknown_employee(db, service):
    with pytest.raises(NotFound):
        await service.bind(555, 999)
    assert db.state.bindings == {}


async def test_bind(db, service):
    employee = await service.add_employee("Иванов Иван")

    assert await service.bind(555, employee.id) == Binding(555, employee.id)
    assert db.state.bindings[555] == Binding(555, employee.id)
