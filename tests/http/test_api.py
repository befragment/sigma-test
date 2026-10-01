from datetime import UTC, datetime

import pytest

from app.domain.models import Message

CHAT_ID = -1001234567890
GROUP = {"chat_id": CHAT_ID, "title": "Пост 1", "window_start": "07:00", "window_end": "10:00"}


class TestAuth:
    async def test_health_is_public(self, client):
        response = await client.get("/health", headers={"X-Admin-Token": ""})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}], ids=["missing", "wrong"])
    @pytest.mark.parametrize("path", ["/groups", "/employees", "/messages"])
    async def test_admin_token_required(self, client, path, headers):
        client.headers.pop("X-Admin-Token")
        response = await client.get(path, headers=headers)
        assert response.status_code == 401


class TestGroups:
    async def test_create_with_defaults(self, client):
        response = await client.post("/groups", json=GROUP)

        assert response.status_code == 200
        assert response.json() == {**GROUP, "window_start": "07:00:00", "window_end": "10:00:00",
                                   "tz": "Europe/Moscow", "active": True}

    async def test_upsert_updates_existing(self, client):
        await client.post("/groups", json=GROUP)
        changed = {**GROUP, "title": "Ночной пост", "window_start": "20:00", "window_end": "08:00",
                   "tz": "Asia/Novosibirsk", "active": False}

        assert (await client.post("/groups", json=changed)).status_code == 200

        [group] = (await client.get("/groups")).json()
        assert (group["title"], group["window_start"], group["tz"], group["active"]) == (
            "Ночной пост", "20:00:00", "Asia/Novosibirsk", False,
        )

    @pytest.mark.parametrize(
        "override",
        [{"window_start": "08:00", "window_end": "08:00"}, {"tz": "Mars/Olympus"},
         {"window_start": "25:00"}, {"title": ""}],
        ids=["equal-bounds", "bad-tz", "bad-time", "empty-title"],
    )
    async def test_validation(self, client, override):
        response = await client.post("/groups", json={**GROUP, **override})
        assert response.status_code == 422
        assert (await client.get("/groups")).json() == []


class TestEmployees:
    async def test_surname_from_full_name(self, client):
        response = await client.post("/employees", json={"full_name": "  Сёмин   Олег Петрович "})

        assert response.status_code == 201
        assert response.json() == {"id": 1, "full_name": "Сёмин Олег Петрович",
                                   "surname_norm": "семин", "active": True}

    async def test_explicit_surname(self, client):
        response = await client.post("/employees", json={"full_name": "Олег Сёмин", "surname": "Сёмин"})
        assert response.json()["surname_norm"] == "семин"

    async def test_list(self, client):
        await client.post("/employees", json={"full_name": "Иванов Иван"})
        await client.post("/employees", json={"full_name": "Петров Пётр"})

        names = [e["full_name"] for e in (await client.get("/employees")).json()]
        assert names == ["Иванов Иван", "Петров Пётр"]

    @pytest.mark.parametrize("body", [{"full_name": ""}, {"full_name": "   "}, {"full_name": "123"}, {}])
    async def test_validation(self, client, body):
        assert (await client.post("/employees", json=body)).status_code == 422


class TestBindings:
    async def test_bind_and_rebind(self, client):
        first = (await client.post("/employees", json={"full_name": "Иванов Иван"})).json()["id"]
        second = (await client.post("/employees", json={"full_name": "Петров Пётр"})).json()["id"]

        response = await client.put("/bindings/555", json={"employee_id": first})
        assert response.status_code == 200
        assert response.json() == {"tg_user_id": 555, "employee_id": first}

        response = await client.put("/bindings/555", json={"employee_id": second})
        assert response.json() == {"tg_user_id": 555, "employee_id": second}

    async def test_unknown_employee(self, client):
        response = await client.put("/bindings/555", json={"employee_id": 999})
        assert response.status_code == 404
        assert "999" in response.json()["detail"]


class TestMessages:
    async def seed(self, app, client) -> int:
        """Группа, сотрудник и три обработанных сообщения: accepted, duplicate, manual_review."""
        await client.post("/groups", json=GROUP)
        employee_id = (await client.post("/employees", json={"full_name": "Мехоношин А"})).json()["id"]
        services = app.state.services
        for message_id, minute, caption in [(10, 50, "Мехоношин"), (11, 55, "Мехоношин"), (12, 58, "кто-то")]:
            await services.ingest.ingest(
                Message(CHAT_ID, message_id, datetime(2025, 9, 19, 5, minute, tzinfo=UTC),
                        tg_user_id=777, caption=caption)
            )
        await services.processing.process_batch()
        return employee_id

    async def test_journal_with_source_link(self, app, client):
        await self.seed(app, client)

        response = await client.get("/messages")

        assert response.status_code == 200
        journal = response.json()
        assert [(m["message_id"], m["status"], m["reason"]) for m in journal] == [
            (12, "manual_review", "employee_not_found"),
            (11, "duplicate", "already_marked"),
            (10, "accepted", "by_caption"),
        ]
        accepted = journal[2]
        assert accepted["link"] == "https://t.me/c/1234567890/10"
        assert accepted["shift_date"] == "2025-09-19"
        assert accepted["caption"] == "Мехоношин"

    async def test_filter_by_status_and_pagination(self, app, client):
        await self.seed(app, client)

        [review] = (await client.get("/messages", params={"status": "manual_review"})).json()
        assert review["message_id"] == 12

        page = (await client.get("/messages", params={"limit": 1, "offset": 1})).json()
        assert [m["message_id"] for m in page] == [11]

    async def test_history_by_employee_and_date(self, app, client):
        employee_id = await self.seed(app, client)

        history = (await client.get(
            "/messages", params={"employee_id": employee_id, "shift_date": "2025-09-19"}
        )).json()

        assert [(m["message_id"], m["status"]) for m in history] == [(11, "duplicate"), (10, "accepted")]

    @pytest.mark.parametrize(
        "params", [{"status": "bogus"}, {"limit": 0}, {"limit": 501}, {"offset": -1}],
        ids=["bad-status", "zero-limit", "big-limit", "negative-offset"],
    )
    async def test_validation(self, client, params):
        assert (await client.get("/messages", params=params)).status_code == 422
