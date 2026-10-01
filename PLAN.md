# PLAN.md — табель смен по фото из Telegram

Рабочий план и журнал для агентов. Источник требований: `CLAUDE.md` (решения заказчика, приоритетнее всего) и `tz.xlsx`
(листы «Задача», «Табель», «Пример сообщ»). В CLAUDE.md файл ТЗ упоминается как `docs/task.xlsx`; на шаге 1 он копируется туда.

**Правило работы:** берёшь первый шаг со статусом `[ ]`, делаешь, прогоняешь тесты, ставишь `[x]` и дописываешь запись
в «Журнал» (что сделано, что не сделано, на что обратить внимание). Решения, которые не очевидны из CLAUDE.md, пиши в
раздел «Решения и допущения» — оттуда они потом переносятся в README.

**Договорённости с пользователем:**
- Один шаг за раз: после каждого шага — коммит и **остановка**, ждать подтверждения пользователя перед следующим.
- Git: один коммит на шаг, сообщение вида `step N: <кратко>`.
- Postgres для тестов и запуска — через Docker Desktop (`docker compose up -d postgres`); локальный Python — 3.12
  из Homebrew (`/opt/homebrew/bin/python3.12`), venv в `.venv`.

---

## Ключевые выжимки из ТЗ

- Отметка = фото с подписью в рабочем чате в момент заступления → `1` в табеле на дату смены (разд. 1, 2).
- Сотрудник не определён однозначно → не ставить 1, отдельный статус ручной проверки (разд. 6, 15).
- Окно времени и правила даты смены настраиваются по группе, учитывать смены через полночь (разд. 7).
- Повторная обработка/публикация не создаёт вторую отметку; дубль фиксируется в журнале (разд. 4.3, 8.2).
- Журнал всех сообщений: статус, причина, ссылка на первоисточник, история по сотруднику и дате (разд. 10).
- 200 групп, тысячи фото в сутки на группу, события не теряются, очередь с гарантированной обработкой (разд. 11).
- Приложение 1 (минимум данных на отметку): ID сообщения, группа, дата/время, сотрудник, дата смены, статус,
  основание (ссылка, подпись, комментарий системы). Объект охраны — необязательно, вне скоупа.
- Пример: подпись «Мехоношин», 19.09.2025 08:50:06 МСК → 1 в колонке 19.
- Лист «Табель»: A2 «Ф.И.О.», B2..AF2 = 1..31, AG2 «кол.\nсмен» (`=SUM(Bn:AFn)`), последняя строка «ИТОГ:» с
  `=SUM(B3:Bk)` по каждому столбцу включая AG; заголовки жирные, серая заливка `D8D8D8`, ширина A≈20.57, дни≈4.71,
  AG≈9.14, строка 1 B1:AG1 объединена (под заголовок месяца). В шаблоне Times New Roman, но по CLAUDE.md — **Arial**.

---

## Шаги

### 1. [x] Каркас проекта и инфраструктура
- `pyproject.toml` (Python 3.12; зависимости: fastapi, uvicorn, aiogram 3, sqlalchemy[asyncio] 2, asyncpg,
  pydantic-settings, openpyxl; dev: pytest, pytest-asyncio, httpx).
- `app/config.py` (Settings: `DATABASE_URL`, `BOT_TOKENS` (через запятую, может быть пустым → бот не запускается),
  `ADMIN_TOKEN`, `WORKERS`, `BATCH_SIZE`, `POLL_INTERVAL`), `app/db.py` (engine, sessionmaker).
- Пустые пакеты `app/domain`, `app/repositories`, `app/services`, `app/handlers/{telegram,http,worker}`.
- `Dockerfile`, `docker-compose.yml` (app + postgres с healthcheck, отдельная БД/схема под тесты), `.env.example`.
- `tests/conftest.py`: фикстура БД по `TEST_DATABASE_URL`, skip если недоступна; `pytest.ini` с `asyncio_mode=auto`.
- `docs/task.xlsx` ← копия `tz.xlsx`.
- **Готово, когда:** `pip install -e .[dev]` и `pytest` проходят (0 тестов), `docker compose up postgres` поднимается.

### 2. [x] Домен: сущности, правила, `decide()` + unit-тесты
- `domain/models.py`: dataclass `Message`, `Attendance`, `Employee`, `Group`, `Binding`, `Decision`;
  `MessageStatus`, `Reason` (Enum); `domain/errors.py`: `NotFound`, `InvalidState`, `ValidationError`.
- `domain/rules.py`: `normalize_word`, `caption_words`, `surname_norm(full_name, surname=None)`,
  `shift_date(sent_at_utc, group)` (окно в сутках / через полночь / вне окна → None), `message_link(chat_id, message_id)`,
  `decide(message, group, employees_by_surname, binding_employee_id) -> Decision` — порядок проверок строго по CLAUDE.md.
- `domain/ports.py`: Protocol для репозиториев и `UnitOfWork`.
- Тесты `tests/domain/`: все пункты из раздела «Тесты» CLAUDE.md + пример «Мехоношин 08:50 МСК».
- **Готово, когда:** все ветки decide покрыты, в `app/domain` нет импортов sqlalchemy/aiogram/fastapi/openpyxl.

### 3. [ ] Сквозной путь на одном кейсе (фото с фамилией → 1 в attendance)
- `repositories/orm.py` (таблицы из «Модели данных», `UNIQUE(chat_id,message_id)`, частичный индекс
  `WHERE status='new'`, `UNIQUE(employee_id, shift_date)`), маппинг ORM ↔ домен.
- `MessageRepository` (add_if_absent, take_new_batch FOR UPDATE SKIP LOCKED, save_decision),
  `AttendanceRepository.mark_if_absent -> bool`, `EmployeeRepository`, `GroupRepository`, `BindingRepository`
  (только нужные методы), `SqlAlchemyUnitOfWork`.
- `IngestService`, `ProcessingService.process_batch()`; `handlers/telegram` (роутер только на фото в group/supergroup),
  `handlers/worker` (цикл с паузой при пустой очереди); `main.py` (composition root, lifespan: create_all, поллинг,
  N воркеров, корректная остановка).
- Интеграционный тест: ingest → process_batch → строка в attendance, message.status=accepted.
- **Готово, когда:** тест зелёный на реальном Postgres.

### 4. [ ] Устойчивость обработки + тесты сервисов на фейках
- Ошибка одного сообщения не роняет пачку: savepoint на сообщение, статус `error`, reason = текст ошибки.
- Дубль за день → `duplicate`; manual_review сохраняет shift_date.
- `tests/fakes.py`: in-memory репозитории и FakeUoW; `tests/services/`: оркестрация, ошибка одного сообщения, дубли.

### 5. [ ] Интеграционные тесты репозиториев (Postgres)
- Идемпотентность приёма (повторный insert того же (chat_id,message_id) — одна строка).
- Дубль отметки за один день.
- Два параллельных воркера × 100 сообщений: каждое обработано ровно один раз, лишних отметок нет.

### 6. [ ] HTTP API: справочники, журнал, health
- `DirectoryService`; роутеры `groups` (POST upsert, GET; start==end → 422), `employees` (POST, GET),
  `bindings` (PUT /bindings/{tg_user_id}), `messages` (GET ?status&limit&offset, ссылка на первоисточник),
  `health`; зависимость `X-Admin-Token`; доменные исключения → HTTP-коды в одном месте.
- Тесты через httpx на реальных сервисах и тестовой БД.

### 7. [ ] Ручная проверка (review)
- `ReviewService`: list, approve(id, employee_id, shift_date?) → attendance manual=true или `duplicate` при конфликте,
  reject → `rejected/manual_rejected`. Approve/reject только из `manual_review`, иначе `InvalidState` → 409.
- Роутер `review`; тесты на фейках и HTTP-тест approve.

### 8. [ ] Табель xlsx
- `services/timesheet_xlsx.py` (чистый билдер openpyxl, без БД) по формату листа «Табель»; `TimesheetService`;
  `GET /timesheet?month=YYYY-MM&chat_id=` → xlsx.
- Тест: единица в нужной ячейке, формулы `SUM` по строке и «ИТОГ:», несуществующие дни серые, шрифт Arial.

### 9. [ ] Запуск в docker-compose, сквозной Telegram-тест, README
- Один сквозной тест Telegram-хендлера с имитированным `Update` (feed_update без сети).
- Проверить `docker compose up` вживую (health, curl-сценарий из README).
- README на русском — все пункты из раздела «README» CLAUDE.md.

### 10. [ ] Финальная проверка
- Полный прогон тестов; grep-проверка правил слоёв (sqlalchemy только в repositories/db/config; aiogram/fastapi
  только в handlers/main); удалить мусор; сверить README с фактическим поведением.

---

## Решения и допущения (дополняется по ходу)

- Сотрудник в табеле выводится по `full_name` (в шаблоне только фамилии — ФИО информативнее при однофамильцах).
- `GET /timesheet` без `chat_id`: все активные сотрудники + все, у кого есть отметки в месяце. С `chat_id`: только
  сотрудники с отметками в этом чате (связь через `attendance.message_id → messages.chat_id`).
- Ручной approve тоже ссылается на исходное сообщение (`attendance.message_id`), `manual=true`.
- Сообщения без автора (анонимный админ, пост от имени канала) принимаются с `tg_user_id = NULL`.
- Обрабатываются только `photo`; изображение, отправленное файлом (document), не считается (вне скоупа v1).
- Справочники (группы/сотрудники/привязки) воркер читает на каждую пачку — для v1 достаточно, кэш вне скоупа.
- Пустой `BOT_TOKENS` → сервис стартует без поллинга (удобно для локальной разработки и тестов).
- Приложение создаётся фабрикой `create_app(settings)`, модульного `app` нет (импорт не требует env);
  uvicorn запускается как `uvicorn --factory app.main:create_app`.
- Окно смены сравнивается с точностью до минуты, обе границы включительно (окно 07:00–10:00 принимает 10:00:59).
  Наивный `sent_at` считается UTC.
- Слова подписи: буквы с дефисом внутри (двойные фамилии), цифры/эмодзи/пунктуация отбрасываются; сопоставление
  только точное (склонения вроде «Мехоношина» не совпадают → `employee_not_found`).
- `decide()` получает `EmployeeIndex` (только активные сотрудники). Привязка аккаунта к неактивному сотруднику
  игнорируется, уволенный не матчится по подписи.
- Правило альбома срабатывает только при пустой подписи и без привязки; альбом с нераспознанной подписью →
  `manual_review/employee_not_found`. Пустая подпись = `None`, `""` или только пробелы.
- Для `manual_review` `employee_id` не заполняется (сотрудника выбирает оператор в approve), `shift_date` — всегда.
  `rejected/album_part_without_caption` тоже сохраняет `shift_date`; `unknown_group` и `outside_window` — нет.
- Дополнительные причины сверх CLAUDE.md: `already_marked` (статус duplicate), `manual_approved`, `manual_rejected`,
  `processing_error` (в `reason` пишется `processing_error: <текст исключения>`, поэтому `Message.reason` — строка).
- Инварианты группы (start != end, существующая таймзона) проверяются в `Group.__post_init__` → `ValidationError`.
- `TEST_DATABASE_URL` по умолчанию `postgresql+asyncpg://timesheet:timesheet@localhost:5432/timesheet_test`;
  БД `timesheet_test` создаётся init-скриптом `docker/initdb.sql` при первом старте volume.

---

## Журнал

_Формат записи:_

```
### Шаг N — YYYY-MM-DD
Сделано: ...
Тесты: X passed / Y skipped (команда запуска)
Не сделано / долги: ...
Заметки для следующего агента: ...
```

### Шаг 1 — 2026-10-01
Сделано: `pyproject.toml` (зависимости + dev, настройки pytest: `asyncio_mode=auto`), `app/config.py` (Settings,
`BOT_TOKENS` через запятую → список), `app/db.py` (engine, session factory), минимальный `app/main.py`
(`create_app` + lifespan с engine), пустые пакеты слоёв, `Dockerfile`, `docker-compose.yml` (postgres:16-alpine с
healthcheck и пробросом 5432, app с `depends_on: service_healthy`), `docker/initdb.sql`, `.env.example`,
`.dockerignore`, `docs/task.xlsx`, `tests/conftest.py` (фикстуры `database_url` — skip при недоступной БД, `engine` с
NullPool), `tests/test_smoke.py`.
Тесты: 3 passed (`.venv/bin/pytest -q`); без Postgres — 2 passed, 1 skipped.
Проверено вручную: `docker compose up -d --wait postgres` → healthy, БД `timesheet_test` есть;
`docker compose up --build app` → образ собирается, uvicorn стартует, `/docs` отдаёт 200.
Не сделано / долги: `/health` и сборка зависимостей — на шагах 3 и 6. `handlers/telegram.py` и `handlers/worker.py`
будут модулями (создаются на шаге 3), `handlers/http/` — пакет под роутеры.
Заметки для следующего агента: venv — `.venv` (Python 3.12, Homebrew). Postgres оставлен запущенным
(`docker compose ps`). Версии на момент установки: aiogram 3.31, fastapi 0.142, SQLAlchemy 2.1, pydantic 2.13,
pytest-asyncio 1.4. `.env` создан из `.env.example` (в git не попадает). Фикстура `engine` — function-scoped с
NullPool, чтобы не ловить проблемы event loop между тестами.

### Шаг 2 — 2026-10-01
Сделано: `app/domain/errors.py` (DomainError, NotFound, InvalidState, ValidationError), `app/domain/models.py`
(Group/Employee/Binding/Message/Attendance/Decision, MessageStatus, Reason, EmployeeIndex), `app/domain/rules.py`
(`normalize_word`, `caption_words`, `surname_norm`, `shift_date`, `message_link`, `decide`), `app/domain/ports.py`
(Protocol репозиториев, UnitOfWork, UnitOfWorkFactory). Добавлена зависимость `tzdata` (для slim-образа).
Тесты: 74 passed (`.venv/bin/pytest -q`): `tests/domain/test_rules.py` (нормализация, окно в сутках, через полночь
с обеих сторон, TZ, валидация группы, ссылки), `tests/domain/test_decide.py` (пример из ТЗ + каждая ветка decide,
пустая подпись, альбом, однофамильцы, неактивные), `tests/domain/test_purity.py` (AST-проверка: в домене нет
sqlalchemy/aiogram/fastapi/openpyxl/pydantic; проверено, что тест ловит нарушение).
Не сделано / долги: Protocol-ы в `ports.py` — черновые, на шаге 3–4 уточнить по факту (в т.ч. savepoint для изоляции
ошибки одного сообщения). Расчёт дней месяца для табеля — на шаге 8.
Заметки для следующего агента: `decide(message, group, EmployeeIndex.build(employees), bound_employee_id)` —
сервис сам находит `bound_employee_id` по `message.tg_user_id` в привязках. `Message` — mutable dataclass (сервис
проставляет результат и отдаёт в `save_result`), остальные сущности frozen. AttendanceRepository отдаёт отметки
за период `list_between(start, end, chat_id)`, а не «за месяц» — месяц считает сервис табеля.
