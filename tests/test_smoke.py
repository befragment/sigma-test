from sqlalchemy import text

from app.config import Settings


def test_bot_tokens_are_split_by_comma():
    settings = Settings(admin_token="x", bot_tokens=" a:1, b:2 ,,")
    assert settings.bot_tokens == ["a:1", "b:2"]


def test_empty_bot_tokens():
    assert Settings(admin_token="x", bot_tokens="").bot_tokens == []


async def test_database_is_reachable(engine):
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT 1")) == 1
