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

### 3. [x] Сквозной путь на одном кейсе (фото с фамилией → 1 в attendance)
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

### 4. [x] Устойчивость обработки + тесты сервисов на фейках
- Ошибка одного сообщения не роняет пачку: savepoint на сообщение, статус `error`, reason = текст ошибки.
- Дубль за день → `duplicate`; manual_review сохраняет shift_date.
- `tests/fakes.py`: in-memory репозитории и FakeUoW; `tests/services/`: оркестрация, ошибка одного сообщения, дубли.

### 5. [x] Интеграционные тесты репозиториев (Postgres)
- Идемпотентность приёма (повторный insert того же (chat_id,message_id) — одна строка).
- Дубль отметки за один день.
- Два параллельных воркера × 100 сообщений: каждое обработано ровно один раз, лишних отметок нет.

### 6. [x] HTTP API: справочники, журнал, health
- `DirectoryService`; роутеры `groups` (POST upsert, GET; start==end → 422), `employees` (POST, GET),
  `bindings` (PUT /bindings/{tg_user_id}), `messages` (GET ?status&limit&offset, ссылка на первоисточник),
  `health`; зависимость `X-Admin-Token`; доменные исключения → HTTP-коды в одном месте.
- Тесты через httpx на реальных сервисах и тестовой БД.

### 7. [x] Ручная проверка (review)
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
- aiogram подтверждает апдейт (offset) до завершения хендлера, поэтому исключение в хендлере = потеря события.
  `IngestService` повторяет сохранение с паузами 0.5…60 с (~2 мин суммарно, хендлеры идут как отдельные задачи и не
  блокируют поллинг); после исчерпания попыток сообщение целиком пишется в лог ERROR. Остаточный риск (БД лежит
  дольше 2 мин или процесс упал во время повторов) — в README.
- Воркер при сбое пачки логирует и спит `POLL_INTERVAL`; транзакция пачки откатывается, сообщения остаются `new`.
- Справочники (группы, привязки, сотрудники) воркер читает целиком на каждую пачку.
- Поллинг: `allowed_updates=["message"]` (правки сообщений не нужны), `handle_signals=False` (сигналы обрабатывает
  uvicorn). Остановка: `stop_polling()` → дождаться поллинга → отменить воркеры → `engine.dispose()`.
- Ошибка одного сообщения: его изменения откатываются savepoint-ом, статус `error`, `reason =
  "processing_error: <Класс>: <текст>"` (до 1000 символов), employee_id/shift_date очищаются. Повторно такие сообщения
  автоматически не обрабатываются (не зацикливаемся на «ядовитых»); вернуть в очередь — вручную (вне скоупа v1).
- Сбой всей пачки (например, потеря соединения) — откат, сообщения остаются `new`, воркер повторит.
- **Защита от deadlock между воркерами:** `ProcessingService` сначала считает решения по всей пачке, затем ставит
  отметки в едином порядке `(employee_id, shift_date)` (сортировка стабильная → внутри пачки отметку получает более
  раннее сообщение). Без этого пачки с одними сотрудниками в разном порядке взаимно блокировались на уникальном
  индексе attendance, и Postgres обрывал одну транзакцию (`deadlock detected` → сообщение в `error`). Между пачками
  отметку получает та транзакция, что закоммитилась первой.
- Журнал (`GET /messages`) живёт в `ReviewService` (экран оператора); отдельного сервиса под него нет.
  Сверх CLAUDE.md добавлены фильтры `employee_id` и `shift_date` — «история по сотруднику и дате» из разд. 10 ТЗ.
  Сортировка — новые сверху, `limit` 1..500 (по умолчанию 50).
- HTTP-коды: нет/неверный `X-Admin-Token` → 401 (сравнение через `secrets.compare_digest`); `NotFound` → 404,
  `InvalidState` → 409, доменная `ValidationError` → 422 (как и ошибки pydantic). `POST /groups` (upsert) → 200,
  `POST /employees` → 201. `/health` — liveness без проверки БД.
- `full_name` сотрудника нормализуется по пробелам; ФИО без букв → 422. Сотрудники только создаются (деактивация и
  правка — вне скоупа v1, поле `active` есть в модели).
- Approve/reject — только из `manual_review` (иначе 409). Переопределить `rejected` (например, `outside_window` —
  поздний выход) или `error` вручную нельзя — вне скоупа v1. Строка сообщения блокируется (`get_for_update`), поэтому
  одновременные решения двух операторов не проходят оба.
- Approve: `shift_date` из запроса или рассчитанная; неактивный сотрудник → 422; отметка `manual=true`, ссылается
  на это же сообщение; при существующей отметке → `duplicate/already_marked`. Reject → `rejected/manual_rejected`,
  рассчитанная `shift_date` остаётся в журнале. Кто принял решение — не хранится (один админ-токен, ролей нет).
- `GET /review` — как журнал: новые сверху, `limit`/`offset`.
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

### Шаг 3 — 2026-10-01
Сделано: `app/repositories/orm.py` (5 таблиц, `uq_messages_chat_message`, частичный `ix_messages_new WHERE
status='new'`, `ix_messages_status_id`, `uq_attendance_employee_date`, `create_schema`), `messages.py`
(add_if_absent через ON CONFLICT DO NOTHING RETURNING, take_new_batch FOR UPDATE SKIP LOCKED, get_for_update,
save_result, list), `attendance.py` (add_if_absent, list_between с фильтром по chat_id через join messages),
`directory.py` (группы upsert/list, сотрудники add/get/list, привязки set (upsert)/list), `uow.py`
(SqlAlchemyUnitOfWork). Сервисы `services/ingest.py` (с повторами), `services/processing.py` (decide + отметка +
статус в одной транзакции, duplicate при конфликте). Хендлеры `handlers/telegram.py` (`create_dispatcher`: только
F.photo в group/supergroup → IngestService), `handlers/worker.py` (`run_worker`). `main.py`: `Services` в
`app.state.services`, lifespan: create_schema → N воркеров → поллинг всех ботов одним Dispatcher.
Тесты: 77 passed. `tests/integration/test_pipeline.py`: ingest → process_batch → строка в attendance (пример
«Мехоношин» 08:50 МСК → 19.09), пустая очередь, lifespan с 2 воркерами сам разбирает очередь. `conftest.py`:
схема пересоздаётся один раз за прогон, перед каждым тестом TRUNCATE ... RESTART IDENTITY; фикстура `uow_factory`.
Проверено вручную: индексы в БД соответствуют плану; `docker compose up --build app` стартует; с невалидным
токеном ошибка `TelegramUnauthorizedError` логируется, сервис продолжает работать и корректно останавливается.
Не сделано / долги: ошибка одного сообщения пока роняет всю пачку (шаг 4 — savepoint). Тест повторов IngestService —
шаг 4 на фейках. Один невалидный токен в `BOT_TOKENS` останавливает поллинг всех ботов (aiogram делает get_me для
всех сразу) — описать в README или запускать поллинг по боту отдельно. HTTP-ручки и /health — шаг 6.
Заметки для следующего агента: репозитории справочников лежат в одном `repositories/directory.py` (три класса).
Для тестов приложения: `Settings(_env_file=None, ...)`, чтобы не подхватывать локальный `.env`; lifespan запускается
через `app.router.lifespan_context(app)`. Postgres из compose продолжает работать.

### Шаг 4 — 2026-10-01
Сделано: `UnitOfWork.savepoint()` (Protocol + `session.begin_nested()` в SqlAlchemyUnitOfWork);
`ProcessingService` обрабатывает каждое сообщение в своём savepoint, при исключении пишет статус `error` с текстом
ошибки и продолжает пачку. `tests/fakes.py`: FakeDB + in-memory репозитории + FakeUnitOfWork (транзакции через
снимки состояния, savepoint откатывает свои изменения), точки внедрения сбоев (`fail_ingests`,
`fail_attendance_for`, `fail_groups_list`).
Тесты: 92 passed. `tests/services/test_processing.py` (отметка, привязка, дубль в одной пачке и между пачками,
повторно не берётся, manual_review с датой без отметки, unknown_group, ошибка одного сообщения с откатом частичной
записи, сбой пачки → всё остаётся new, размер пачки и порядок по id), `tests/services/test_ingest.py` (new,
повторная доставка, повторы до восстановления, отказ после всех попыток),
`tests/integration/test_processing_errors.py` (на Postgres: `SELECT 1/0` внутри обработки одного сообщения не
abort-ит транзакцию пачки). Мутационная проверка: без savepoint падают оба теста на изоляцию ошибки.
Не сделано / долги: нет ручки «вернуть error в очередь» (осознанно, в README). Тест параллельных воркеров — шаг 5.
Заметки для следующего агента: в фейках `put()`/`db.add_employee()` пишут сразу в «закоммиченное» состояние;
сервис работает через `db.uow` (фабрика). Порядок полей у `Message` позиционный: chat_id, message_id, sent_at.

### Шаг 5 — 2026-10-01
Сделано: `tests/integration/test_repositories.py` — идемпотентность приёма (повтор, другой чат, 10 одновременных
доставок → одна строка), уникальность отметки (повтор, конкурентная вставка ждёт первую транзакцию, дубль за день
через обработку), очередь (SKIP LOCKED даёт непересекающиеся пачки, блокировка снимается после отката),
**два параллельных воркера × 200 сообщений** (20 сотрудников × 2 дня × 5 фото, перемешаны: сумма обработанных = 200,
40 accepted / 160 duplicate, 40 отметок, каждая ссылается на accepted-сообщение), справочники (upsert группы при
объекте в identity map, перепривязка аккаунта).
Найдено и исправлено: deadlock между воркерами при пересекающихся пачках (тест
`test_crossed_lock_order_does_not_deadlock` детерминированно воспроизводит его через барьер: до исправления
`DeadlockDetectedError` → сообщение в error). Исправление — порядок вставки отметок, см. «Решения».
Тесты: 104 passed (~8 с, из них ~5 с — конкурентные тесты). Конкурентные тесты прогнаны 8 раз подряд — стабильно.
Мутационные проверки: без `FOR UPDATE SKIP LOCKED` тест воркеров падает (396 обработок на 200 сообщений).
Не сделано / долги: нет.
Заметки для следующего агента: фикстура `engine` использует NullPool — каждый UoW открывает своё соединение, поэтому
«параллельные воркеры» в одном event loop действительно работают в разных транзакциях Postgres.

### Шаг 6 — 2026-10-01
Сделано: `services/directory.py` (upsert_group, list_groups, add_employee, list_employees, bind с проверкой
сотрудника), `services/review.py` (пока только `list_messages`; approve/reject — шаг 7). Фильтры `employee_id`,
`shift_date` в `MessageRepository.list` (Protocol, SQL, фейк). HTTP-слой `app/handlers/http/`: `schemas.py`
(pydantic In/Out, `MessageOut.link` через `domain.rules.message_link`), `deps.py` (`require_admin`, `Directory`,
`Review` из `app.state.services`), `errors.py` (единая трансляция DomainError → код), роутеры `groups`,
`employees`, `bindings`, `messages`, `health`; `register_http(app)` вешает admin-зависимость на всё, кроме /health.
`main.py`: `Services` расширен, `app.state.settings` выставляется в `create_app`.
Тесты: 143 passed. `tests/http/` (httpx + ASGITransport на реальных сервисах и тестовой БД, lifespan с
`workers=0`): авторизация, группы (создание, upsert, 4 вида ошибок валидации), сотрудники, привязки (перепривязка,
404), журнал (ссылка на первоисточник, фильтр по статусу, пагинация, история по сотруднику и дате, валидация
параметров). `tests/services/test_directory.py` на фейках. `tests/domain/test_purity.py` заменён на
`tests/test_layers.py` — AST-проверка правил слоёв для domain/services/repositories (проверено, что ловит нарушение).
Проверено вручную: `/openapi.json` генерируется, все пути на месте.
Не сделано / долги: нет.
Заметки для следующего агента: в FastAPI 0.142 `app.routes` содержит `_IncludedRouter` вместо APIRoute — для
проверки маршрутов смотри `/openapi.json`. HTTP-тесты сами разбирают очередь через
`app.state.services.processing.process_batch()` (воркеров нет), сообщения кладут через `services.ingest`.

### Шаг 7 — 2026-10-01
Сделано: `ReviewService` — `list_review`, `approve(id, employee_id, shift_date?)`, `reject(id)` (общая проверка
статуса с блокировкой строки в `_take_for_review`, внедряемые часы). HTTP `app/handlers/http/review.py`:
`GET /review`, `POST /review/{id}/approve` (`ApproveIn`), `POST /review/{id}/reject`.
Тесты: 169 passed. `tests/services/test_review.py` (фейки: список, approve с отметкой manual, явная дата, дубль,
нет даты, 5 недопустимых статусов, неизвестные сообщение/сотрудник, неактивный сотрудник, reject, повторное
решение), `tests/http/test_review.py` (список со ссылкой, approve → отметка manual в БД, дубль, явная дата, reject,
409/404, 422, токен), `tests/integration/test_review.py` (два approve и reject одновременно → проходит ровно одно).
Мутационная проверка: без `FOR UPDATE` в `get_for_update` проходят все три решения — тест падает.
Не сделано / долги: нет.
Заметки для следующего агента: отметки в HTTP-тестах проверяются через фикстуру `uow_factory` (та же тестовая БД).
