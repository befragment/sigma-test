"""Домен не зависит от инфраструктуры: проверяем импорты по исходникам."""

import ast
from pathlib import Path

import app.domain

FORBIDDEN = {"sqlalchemy", "aiogram", "fastapi", "openpyxl", "asyncpg", "pydantic", "pydantic_settings"}


def test_domain_has_no_infrastructure_imports():
    violations = []
    for path in Path(app.domain.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            violations += [f"{path.name}: {m}" for m in modules if m.split(".")[0] in FORBIDDEN]
    assert violations == []
