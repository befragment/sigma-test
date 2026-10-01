Ты помогаешь мне сделать тестовое задание. Ниже контекст, принятые решения и ограничения. Вопросов мне не задавай: если чего-то не хватает, прими разумное допущение и запиши его в README.

## Задача
Система автоматического заполнения табеля смен по сообщениям из Telegram-групп. Фото с подписью, опубликованное в рабочем чате в момент заступления на смену, означает отметку 1 в табеле на этой дате. Полное ТЗ лежит в docs/task.xlsx (листы «Задача», «Табель», «Пример сообщ»). Прочитай его целиком перед началом, особенно разделы 4, 6–10, 15, 16.

Нагрузка: до 200 групп, тысячи фото в сутки в каждой, события не теряются, повторная обработка не создаёт дублей.

## Стек (не менять)
- Python 3.12, FastAPI, aiogram 3 (long polling), PostgreSQL, async SQLAlchemy 2 + asyncpg, pydantic-settings, openpyxl, pytest + pytest-asyncio.
- Один сервис в одном процессе: lifespan FastAPI запускает поллинг бота и N воркеров как фоновые asyncio-задачи.
- Запуск: docker-compose (app + postgres с healthcheck), настройки через .env (есть .env.example).
- Миграции: на этой версии достаточно Base.metadata.create_all при старте, это зафиксировать в README как упрощение.

## Архитектура
1. Приём: aiogram-хендлер реагирует только на сообщения с фото в группах и супергруппах. Он ничего не вычисляет: пишет строку в messages (chat_id, message_id, tg_user_id, media_group_id, caption, sent_at в UTC) через INSERT ... ON CONFLICT (chat_id, message_id) DO NOTHING со статусом new. Фото не скачивать.
2. Очередь: таблица messages со статусами. Воркеры берут пачки через SELECT ... WHERE status='new' ORDER BY id LIMIT N FOR UPDATE SKIP LOCKED, обрабатывают в одной транзакции и ставят итоговый статус. Нескольких воркеров и нескольких реплик не должно быть проблемой.
3. Решение по сообщению оформить чистой функцией без БД и Telegram (decide), принимающей всё нужное аргументами и возвращающей Decision (status, reason, employee_id, shift_date). Это главный объект для unit-тестов.
4. Табель: таблица attendance с UNIQUE (employee_id, shift_date), запись через ON CONFLICT DO NOTHING RETURNING. Если запись уже есть, сообщение получает статус duplicate.
5. Токены бота: BOT_TOKENS через запятую, один Dispatcher, start_polling(*bots). Дубли от нескольких ботов в одной группе снимаются уникальностью (chat_id, message_id).

## Слои и структура проекта

Код разделён на четыре слоя. Зависимости направлены только вниз: handlers → services → repositories → domain. Домен не зависит ни от чего.

app/
  domain/         сущности, статусы, правила, чистая логика
  repositories/   доступ к БД
  services/       сценарии (use cases)
  handlers/       точки входа: Telegram, HTTP, воркер
  main.py         composition root: сборка зависимостей и lifespan
  config.py, db.py

### domain
- Dataclass-сущности (Message, Attendance, Employee, Group, Binding), статусы и причины как Enum, доменные исключения (NotFound, InvalidState и т.п.).
- Вся бизнес-логика без ввода-вывода: decide(), расчёт даты смены по окну группы (включая окно через полночь), нормализация и сопоставление фамилий, построение ссылки на сообщение.
- Интерфейсы репозиториев и Unit of Work описаны здесь как Protocol.
- Нет импортов sqlalchemy, aiogram, fastapi, openpyxl.

### repositories
- Единственное место, где есть SQL и ORM-модели SQLAlchemy. Репозитории возвращают доменные сущности, а не ORM-объекты (маппинг внутри).
- По одному репозиторию на агрегат: MessageRepository (добавить, если нет; забрать пачку new через FOR UPDATE SKIP LOCKED; сохранить решение; список по статусу; получить с блокировкой), AttendanceRepository (поставить отметку, если нет, и вернуть, создана ли она; отметки за месяц), EmployeeRepository, GroupRepository, BindingRepository.
- Идемпотентность (ON CONFLICT DO NOTHING) реализуется здесь и скрыта за понятными методами.
- Без generic-базового репозитория: только методы, которые реально нужны сервисам.

### Unit of Work
- Один объект на транзакцию, отдаёт репозитории и управляет commit/rollback. Сервисы получают фабрику UoW и никогда не принимают session напрямую.
- Граница транзакции задаётся в сервисе, не в хендлере и не в репозитории.

### services
- IngestService: принять сообщение из Telegram и сохранить как new.
- ProcessingService: забрать пачку, загрузить справочники (группы, привязки, сотрудники), вызвать decide, записать отметку и статус, обработать ошибку отдельного сообщения, не роняя пачку.
- ReviewService: список спорных, approve, reject.
- DirectoryService: группы, сотрудники, привязки.
- TimesheetService: собрать данные за месяц и отдать в билдер xlsx. Сам билдер xlsx (openpyxl) отдельный модуль без обращения к БД.
- Сервисы оркестрируют, но не содержат правил из domain и не пишут SQL.

### handlers
- Тонкий слой: разобрать вход, вызвать сервис, оформить ответ. Бизнес-логики и SQL нет.
- telegram: aiogram-роутер, только фото в группах, вызывает IngestService.
- http: FastAPI-роутеры по ресурсам (groups, employees, bindings, messages, review, timesheet, health), проверка X-Admin-Token как зависимость. Доменные исключения переводятся в HTTP-коды в одном месте (exception handlers).
- worker: цикл воркера, вызывает ProcessingService.process_batch и ждёт, если очередь пуста.

### Сборка зависимостей
- Всё собирается в main.py через конструкторы (db → UoW → сервисы → хендлеры). Без DI-фреймворка. FastAPI Depends только достаёт готовые сервисы из app.state.

### Правила
- sqlalchemy импортируется только в repositories, db.py и config. aiogram и fastapi только в handlers и main.py.
- Никакой логики в хендлерах и в репозиториях.
- Не добавлять лишнего: никакого CQRS, event bus, generic-репозиториев и абстракций «на будущее».

### Тесты по слоям
- domain: чистые unit-тесты без БД и моков.
- services: тесты на in-memory fake-репозиториях и fake UoW (оркестрация, обработка ошибки одного сообщения, дубли, approve/reject).
- repositories: интеграционные на реальном Postgres (ON CONFLICT, SKIP LOCKED при двух параллельных воркерах).
- handlers: HTTP-тесты через httpx на реальных сервисах и тестовой БД, один сквозной тест Telegram-хендлера с имитированным update.

## Модель данных
- tg_groups: chat_id (PK), title, tz (по умолчанию Europe/Moscow), window_start, window_end (местное время), active.
- employees: id, full_name, surname_norm (первое слово ФИО, lower, ё→е), active.
- telegram_bindings: tg_user_id (PK), employee_id.
- messages: id, chat_id, message_id, tg_user_id, media_group_id, caption, sent_at, status, reason, employee_id, shift_date, created_at, processed_at; UNIQUE (chat_id, message_id); частичный индекс по id для status='new'.
- attendance: id, employee_id, shift_date, message_id (FK), manual (bool), created_at; UNIQUE (employee_id, shift_date).
Статусы messages: new, accepted, rejected, manual_review, duplicate, error. В reason всегда причина.

## Правила решения (зафиксированы мной)
Порядок проверок в decide:
1. Группа не зарегистрирована или неактивна: rejected, unknown_group.
2. Дата смены по окну группы. Время сообщения переводится в tz группы. Если window_start <= window_end, это окно в пределах суток, и shift_date равна местной дате. Если window_start > window_end, окно через полночь (например 20:00–08:00): время >= start даёт местную дату, время <= end даёт местную дату минус 1 день. Вне окна: rejected, outside_window. start == end запрещать при создании группы.
3. Сотрудник определяется по фамилии из подписи и по Telegram-аккаунту:
   - слова подписи нормализуются (lower, ё→е, без пунктуации), точное совпадение со surname_norm;
   - совпали две и более разные фамилии: manual_review, multiple_employees;
   - совпала одна фамилия, но ей соответствует несколько сотрудников (однофамильцы): если привязка аккаунта указывает на одного из них, берём его, иначе manual_review, ambiguous_surname;
   - совпал один сотрудник, а у аккаунта есть привязка к другому: manual_review, caption_account_mismatch;
   - фамилия не найдена, но аккаунт привязан: accepted, reason by_account (включая пустую подпись);
   - фамилия не найдена, аккаунт не привязан: если подписи нет, manual_review, no_caption, иначе manual_review, employee_not_found;
   - сообщение из альбома (media_group_id) без подписи и без привязки аккаунта: rejected, album_part_without_caption.
4. Во всех остальных случаях accepted с reason by_caption, by_caption_and_account или by_account.
Для manual_review всегда сохранять рассчитанный shift_date.

## API (FastAPI, все ручки кроме /health под заголовком X-Admin-Token из настроек)
- POST /groups (upsert), GET /groups.
- POST /employees (full_name, опционально surname), GET /employees.
- PUT /bindings/{tg_user_id} с employee_id.
- GET /messages?status=&limit=&offset= журнал обработки; в каждой записи ссылка на первоисточник (для chat_id вида -100... это https://t.me/c/{id без -100}/{message_id}).
- GET /review список manual_review.
- POST /review/{id}/approve (employee_id, опционально shift_date): ставит отметку с manual=true, при конфликте статус duplicate.
- POST /review/{id}/reject: rejected, manual_rejected.
- GET /timesheet?month=YYYY-MM&chat_id=: xlsx в формате листа «Табель» из docs/task.xlsx: заголовок «Ф.И.О.», дни 1–31, «кол. смен» с формулой SUM по строке, нижняя строка «ИТОГ:» с суммой по каждому столбцу. Шрифт Arial, несуществующие дни месяца серым.
- GET /health.

## Что НЕ делать (вне скоупа первой версии, перечислить в README)
Fuzzy-поиск фамилий, правки и удаление сообщений, UI, запись в Google Sheets, хранение фото, роли и права кроме админ-токена, привязка к объектам охраны, нагрузочные тесты, миграции Alembic.

## Тесты
Unit для decide (без БД): окно в сутках, окно через полночь на обе стороны границы, вне окна, неизвестная группа, каждая ветка определения сотрудника из списка выше, пустая подпись, альбом.
Интеграционные на реальном Postgres (TEST_DATABASE_URL, пропускать, если недоступен): идемпотентность приёма, дубль за один день, два параллельных воркера по 100 сообщений (каждое обработано ровно один раз, отметок нет лишних), approve из review, содержимое xlsx (единица в нужной ячейке, формулы на месте).
Один тест на пример из ТЗ: сообщение с подписью «Мехоношин» в 08:50 по Москве попадает в табель в день сообщения.

## Порядок работы
1. Сначала сделай сквозной путь на одном кейсе (фото с фамилией превращается в единицу в attendance) и убедись, что он работает.
2. Дальше добавляй ветки и ручки по одной, после каждой запускай тесты.
3. Не усложняй: никаких лишних абстракций, очередей и сервисов сверх описанного.
4. Работа должна укладываться в разумный объём: приоритет у корректности ядра (идемпотентность, правила решения), а не у широты.

## README (на русском)
Что делает система; как запустить (docker-compose up, переменные .env); как настроить бота (отключить privacy mode через BotFather или сделать админом группы, иначе он не видит обычные фото); примеры curl для создания группы, сотрудников, привязки и получения табеля; схема потока сообщения; таблица статусов и причин; принятые допущения; что осознанно не сделано; ответы на открытые вопросы из раздела 16 ТЗ в виде допущений; как масштабировать (webhook, несколько реплик, один поллер на токен).