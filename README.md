# Alfa-Hack

## Стек

- Go 1.27
- `net/http`, `pgx/v5`, UUID
- PostgreSQL 17, Docker Compose

## Запуск через Docker

```bash
docker compose up --build
```

Для проверки сервера используем `GET http://localhost:8080/health`, `GET http://localhost:8080/ready`.

```bash
curl -i "http://localhost:8080/health"
```

```bash
curl -i "http://localhost:8080/ready"
```

Чтобы перезаписать БД используем `docker compose down -v` (удалит локальные данные), затем `docker compose up --build`.

## Локальный запуск

1. Создаем PostgreSQL и применяем `migrations/001_init.sql`.
2. Копируем `.env.example` в `.env` и экспортируем переменные окружения из него.
3. `go mod tidy`
4. `go run ./cmd/api`

## API

- `GET /health` — проверяем, что HTTP-сервер работает. Возвращает статус 200.
- `GET /ready` — проверка подключения к PostgreSQL. В логах возвращает 200.
- `GET /api/v1/companies` — список компаний.
- `GET /api/v1/companies/{uuid}` — информация о конкретной компании.
- `GET /api/v1/companies/{uuid}/feed` — лента новостей, связанная с компанией.
- `GET /api/v1/news?limit=20&offset=0&company_id={uuid}` — список новостей с фильтрацией по компании и пагинацией.
- `GET /api/v1/news/{uuid}` — получение одной конкретной новости по её UUID.
- `GET /api/v1/knowledge?limit=20&offset=0` — получение записей базы знаний с пагинацией.
- `POST /api/v1/companies/{uuid}/analyses` — создание задачи анализа компании. Возвращает `202 Accepted`, если запрос принят в обработку.
- `GET /api/v1/analyses/{uuid}` — получение статуса и сохранённого результата.

Пагинация принимает `limit` от 1 до 100 и `offset` от 0. Ответы — JSON; формат ошибок `{"error":"..."}`. Запросы получают `X-Request-ID`, если ID безопасен, то сохраняем, он же попадает в структурированный JSON-лог.

### Дополнительные эндпоинты

- `POST /api/v1/news/import` — запускает сбор новостей подключёнными коллекторами и сохраняет результаты в PostgreSQL.

## Проверка ручек

Проверка основных сценариев:

```bash
curl -i http://localhost:8080/health
curl -i http://localhost:8080/ready

curl -i http://localhost:8080/api/v1/companies
curl -i "http://localhost:8080/api/v1/news?limit=20&offset=0"
curl -i http://localhost:8080/api/v1/knowledge
```

Проверка импорта новостей:

```bash
curl -i -X POST http://localhost:8080/api/v1/news/import
```

Проверка конкретных объектов:

```bash
curl -i http://localhost:8080/api/v1/companies/<UUID компании>

curl -i http://localhost:8080/api/v1/companies/<UUID компании>/feed

curl -i http://localhost:8080/api/v1/news/<UUID новости>

curl -i -X POST http://localhost:8080/api/v1/companies/<UUID компании>/analyses

curl -i http://localhost:8080/api/v1/analyses/<UUID анализа>
```

## Создание тестовых данных в БД

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "
INSERT INTO companies (name)
VALUES ('Test Company')
RETURNING id, name;
"
```

- Получаем UUID компании.

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "
INSERT INTO sources (name, base_url)
VALUES ('Test Source 2', 'https://example.com')
RETURNING id, name;
"
```

- Получаем UUID источника.

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "
INSERT INTO news (source_id, title, summary, url, published_at)
VALUES (
    '<UUID источника>'::uuid,
    'Вторая тестовая новость',
    'Описание второй тестовой новости',
    'https://example.com/test-news-2',
    NOW()
)
RETURNING id, title, url;
"
```

- Получаем UUID новости.

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "
INSERT INTO company_news (company_id, news_id, relevance_score)
VALUES (
    '<UUID компании>'::uuid,
    '<UUID новости>'::uuid,
    0.9500
);
"
```

## Просмотр тестовых данных напрямую в PostgreSQL

Все компании:

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "SELECT * FROM companies;"
```

Все источники:

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "SELECT * FROM sources;"
```

Все новости:

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "SELECT id, title, url, source_id, published_at FROM news ORDER BY created_at DESC;"
```

Логи:

```bash
docker compose logs --tail=100 backend
```

## Контракт результата анализа

Поля результата: `facts`, `bank_perspective`, `ai_conclusions`, `risks`, `opportunities`, `source_urls`.

Сохранение результата поддерживается репозиторием. Пока только записывает `queued` (задача зарегистрирована как ожидающая выполнения). Сам статус пока ничего не показывает, на данный момент просто заглушка.

## Дополнительная информация о функциональности

### Работа с компаниями

Данные компаний хранятся в PostgreSQL. Для каждой компании доступен отдельный эндпоинт, а также лента связанных с ней новостей.

Связь между компаниями и новостями реализована через таблицу `company_news`. В ней хранится оценка релевантности `relevance_score`.

### Работа с новостями

Новости хранятся в таблице `news` и связаны с источниками через `source_id`.

При получении списка новостей поддерживается пагинация и фильтрация по компании. Для получения одной новости используется её UUID.

В проекте предусмотрена нормализация URL для унификации ссылок и предотвращения дублирования публикаций. Для URL в таблице новостей установлено уникальное ограничение.

### Сбор новостей из внешних источников

Для импорта новостей предусмотрен интерфейс `Collector`, который позволяет подключать разные источники с единым способом получения публикаций. Результаты работы коллекторов передаются в механизм импорта и сохраняются в PostgreSQL.

**Текущий статус интеграции с Альфа-Банком: НЕ РАБОТАЕТ.**

Коллектор обращается к странице `https://alfabank.ru/news/`, однако вместо HTML со списком публикаций сайт возвращает страницу антибот-проверки Servicepipe.


Второй подключённый источник `Mock News Source` возвращает две тестовые публикации. Он предназначен для проверки механизма импорта и сохранения новостей, но не является реальным внешним источником.



### База знаний

Для чтения записей базы знаний используется `GET /api/v1/knowledge`. Поддерживается пагинация с параметрами `limit` и `offset`.

Записи базы знаний предназначены для хранения материалов, которые могут использоваться при последующем анализе компаний.

### Анализ компаний

Создание анализа через `POST /api/v1/companies/{uuid}/analyses` регистрирует задачу для конкретной компании. Для просмотра её состояния используется `GET /api/v1/analyses/{uuid}`.

В контракте результата предусмотрены:

- `facts` — факты;
- `bank_perspective` — позиция банка;
- `ai_conclusions` — выводы ИИ;
- `risks` — риски;
- `opportunities` — возможности;
- `source_urls` — ссылки на источники.

**Важно:** полноценный исполнитель анализа пока не реализован. Создание задачи со статусом `queued` означает только регистрацию задачи. Нельзя считать, что анализ уже выполняется или что результат сформирован.

### HTTP middleware и логирование

В проекте предусмотрена обработка HTTP-запросов с идентификаторами запросов и измерением времени обработки.

- `X-Request-ID` используется для корреляции запроса и связанных с ним логов.
- `X-Response-Time` содержит время обработки запроса.
- Структурированные JSON-логи содержат информацию о запросе, его HTTP-методе, пути, статусе и длительности обработки.
- Заголовки безопасности ограничивают небезопасное использование ответов API в браузере.

### Работа с PostgreSQL и Docker

Приложение использует PostgreSQL 17 и библиотеку `pgx/v5` для работы с базой данных.

`GET /ready` предназначен для проверки доступности базы данных. В отличие от `/health`, который проверяет работоспособность HTTP-сервера, `/ready` позволяет проверить готовность приложения к работе с PostgreSQL.

Для повторной инициализации базы данных можно использовать `docker compose down -v`, однако эта команда удаляет volume с сохранёнными данными. Не используйте её, если нужно сохранить локальную базу.

## Структура

- `cmd/api` — точка входа, graceful shutdown.
- `internal/config` — env-конфигурация.
- `internal/storage` — пул PostgreSQL.
- `internal/http` — маршруты и middleware.
- `internal/{company,news,knowledge,analysis}` — модели, сервисы, репозитории, handlers.
- `migrations` — схема БД.
