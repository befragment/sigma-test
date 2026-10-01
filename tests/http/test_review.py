from datetime import UTC, date, datetime

import pytest

from app.domain.models import Message

CHAT_ID = -1001234567890
GROUP = {"chat_id": CHAT_ID, "title": "Пост 1", "window_start": "07:00", "window_end": "10:00"}
DAY = date(2025, 9, 19)


async def seed(app, client) -> dict[str, int]:
    """Однофамильцы → сообщение «Иванов» уходит на ручную проверку; второе сообщение без подписи — тоже."""
    await client.post("/groups", json=GROUP)
    ids = {}
    for key, full_name in [("ivan", "Иванов Иван"), ("petr", "Иванов Пётр")]:
        ids[key] = (await client.post("/employees", json={"full_name": full_name})).json()["id"]
    for message_id, caption in [(10, "Иванов"), (11, None)]:
        await app.state.services.ingest.ingest(
            Message(CHAT_ID, message_id, datetime(2025, 9, 19, 5, 50, tzinfo=UTC), caption=caption)
        )
    await app.state.services.processing.process_batch()
    review = (await client.get("/review")).json()
    ids.update({f"msg{m['message_id']}": m["id"] for m in review})
    return ids


async def marks(uow_factory):
    async with uow_factory() as uow:
        return await uow.attendance.list_between(date(2025, 9, 1), date(2025, 9, 30), chat_id=None)


async def test_review_list(app, client):
    await seed(app, client)

    review = (await client.get("/review")).json()

    assert [(m["message_id"], m["reason"], m["shift_date"]) for m in review] == [
        (11, "no_caption", "2025-09-19"),
        (10, "ambiguous_surname", "2025-09-19"),
    ]
    assert review[0]["link"] == "https://t.me/c/1234567890/11"


async def test_approve_sets_manual_mark(app, client, uow_factory):
    ids = await seed(app, client)

    response = await client.post(f"/review/{ids['msg10']}/approve", json={"employee_id": ids["petr"]})

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["reason"], body["employee_id"], body["shift_date"]) == (
        "accepted", "manual_approved", ids["petr"], "2025-09-19",
    )
    [mark] = await marks(uow_factory)
    assert (mark.employee_id, mark.shift_date, mark.message_id, mark.manual) == (
        ids["petr"], DAY, ids["msg10"], True,
    )
    assert [m["message_id"] for m in (await client.get("/review")).json()] == [11]


async def test_approve_same_employee_twice_gives_duplicate(app, client, uow_factory):
    ids = await seed(app, client)
    await client.post(f"/review/{ids['msg10']}/approve", json={"employee_id": ids["petr"]})

    response = await client.post(f"/review/{ids['msg11']}/approve", json={"employee_id": ids["petr"]})

    assert (response.json()["status"], response.json()["reason"]) == ("duplicate", "already_marked")
    assert len(await marks(uow_factory)) == 1


async def test_approve_with_explicit_date(app, client, uow_factory):
    ids = await seed(app, client)

    response = await client.post(
        f"/review/{ids['msg11']}/approve", json={"employee_id": ids["ivan"], "shift_date": "2025-09-18"}
    )

    assert response.json()["shift_date"] == "2025-09-18"
    [mark] = await marks(uow_factory)
    assert mark.shift_date == date(2025, 9, 18)


async def test_reject(app, client, uow_factory):
    ids = await seed(app, client)

    response = await client.post(f"/review/{ids['msg10']}/reject")

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["reason"]) == ("rejected", "manual_rejected")
    assert await marks(uow_factory) == []


async def test_errors(app, client):
    ids = await seed(app, client)
    await client.post(f"/review/{ids['msg10']}/reject")

    conflict = await client.post(f"/review/{ids['msg10']}/approve", json={"employee_id": ids["ivan"]})
    assert conflict.status_code == 409
    assert "manual_review" in conflict.json()["detail"]
    assert (await client.post(f"/review/{ids['msg10']}/reject")).status_code == 409
    assert (await client.post("/review/9999/reject")).status_code == 404
    assert (await client.post(f"/review/{ids['msg11']}/approve", json={"employee_id": 9999})).status_code == 404


@pytest.mark.parametrize("body", [{}, {"employee_id": "x"}, {"employee_id": 1, "shift_date": "19.09.2025"}])
async def test_approve_validation(app, client, body):
    ids = await seed(app, client)
    assert (await client.post(f"/review/{ids['msg10']}/approve", json=body)).status_code == 422


async def test_review_requires_token(client):
    client.headers.pop("X-Admin-Token")
    assert (await client.get("/review")).status_code == 401
    assert (await client.post("/review/1/reject")).status_code == 401
