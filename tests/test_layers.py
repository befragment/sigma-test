"""Правила слоёв из CLAUDE.md: зависимости направлены только вниз, инфраструктура — только там, где разрешено."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).parent.parent / "app"

# слой → запрещённые для него пакеты верхнего уровня
FORBIDDEN = {
    "domain": {"sqlalchemy", "asyncpg", "aiogram", "fastapi", "starlette", "openpyxl", "pydantic",
               "pydantic_settings", "app.repositories", "app.services", "app.handlers", "app.main"},
    "services": {"sqlalchemy", "asyncpg", "aiogram", "fastapi", "starlette", "app.repositories",
                 "app.handlers", "app.main"},
    "repositories": {"aiogram", "fastapi", "starlette", "openpyxl", "app.services", "app.handlers",
                     "app.main"},
}


def imports(path: Path) -> list[str]:
    result = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            result += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_imports(layer):
    violations = [
        f"{path.relative_to(APP)}: {module}"
        for path in (APP / layer).rglob("*.py")
        for module in imports(path)
        if any(module == banned or module.startswith(banned + ".") for banned in FORBIDDEN[layer])
    ]
    assert violations == []
