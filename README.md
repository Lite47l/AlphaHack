# Alfa-Hack 

## Стек
- Go 1.27 
- `net/http`, `pgx/v5`, UUID
- PostgreSQL 17, Docker Compose

## Запуск через Docker
```bash
docker compose up --build
```
Для проверки сервера используем  `GET http://localhost:8080/health`, `GET http://localhost:8080/ready`.

```bush
curl -i "http://localhost:8080/health"
```

```bush
curl -i "http://localhost:8080/ready"
```

Чтобы перезаписать БД используем `docker compose down -v` (удалит локальные данные), затем `docker compose up --build`.

## Локальный запуск
1. Создаем PostgreSQL и применяем `migrations/001_init.sql`.
2. Копируем `.env.example` в `.env` и экспортируем переменные окружения из него.
3. `go mod tidy`
4. `go run ./cmd/api`

## API
- `GET /health` - проверяем, что HTTP-сервер работает. Возвращает статус 200
- `GET /ready` - проверка подключения к PostgreSQL. В логах возвращает 200
- `GET /api/v1/companies` - Список компаний
- `GET /api/v1/companies/{uuid}` - Информация о конкретной компании
- `GET /api/v1/companies/{uuid}/feed` - Лента новостей, связанная с компанией
- `GET /api/v1/news?limit=20&offset=0&company_id={uuid}` - список новостей с фильтрацией по компании с пагинацией
- `GET /api/v1/news/{uuid}` - Получение одной конкретной новости по её UUID 
- `GET /api/v1/knowledge?limit=20&offset=0` - Получение записей базы знаний с пагинацией 
- `POST /api/v1/companies/{uuid}/analyses` - Создание задачи анализа компании. Возвращает 202 Accepted, если запрос принят в обработку
- `GET /api/v1/analyses/{uuid}` - Получение статуса и сохранённого результата

Пагинация принимает `limit` от 1 до 100 и `offset` от 0. Ответы — JSON; Формат ошибок `{"error":"..."}`. Запросы получают `X-Request-ID`, если ID безопасен, то сохраняем, он же попадает в структурированный JSON-лог.

## Проверка ручек

Проверка основных сценариев
```bash
curl -i http://localhost:8080/health
curl -i http://localhost:8080/ready

curl -i http://localhost:8080/api/v1/companies
curl -i "http://localhost:8080/api/v1/news?limit=20&offset=0"
curl -i http://localhost:8080/api/v1/knowledge
```

Проверка конкретных объектов

```bash
curl -i http://localhost:8080/api/v1/companies/<UUID компании>

curl -i http://localhost:8080/api/v1/companies/<UUID компании>/feed

curl -i http://localhost:8080/api/v1/news/<UUID новости>

curl -i -X POST http://localhost:8080/api/v1/companies/<UUID компании>/analyses

curl -i http://localhost:8080/api/v1/analyses/<UUID анализа>
```

## Создание тестовых данных в бд

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "
INSERT INTO companies (name)
VALUES ('Test Company')
RETURNING id, name;
"
```

- получаем UUID компании

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "
INSERT INTO sources (name, base_url)
VALUES ('Test Source 2', 'https://example.com')
RETURNING id, name;
"
```

- получаем UUID источника


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

- получаем UUID новости

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

Все компании

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "SELECT * FROM companies;"
```

Все Источники

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "SELECT * FROM sources;"
```

Все новости

```bash
docker compose exec postgres psql -U postgres -d hackathon -c "SELECT id, title, url, source_id, published_at FROM news ORDER BY created_at DESC;"
```

Логи

```bash
docker compose logs --tail=100 backend
```

## Контракт результата анализа
Поля результата: `facts`, `bank_perspective`, `ai_conclusions`, `risks`, `opportunities`, `source_urls`. Сохранение результата поддерживается репозиторием. Пока только записывает `queued` (задача зарегистрирована как ожидающая выполнения). Сам статус пока ничего не показывает, на данный момент просто заглушка.

## Структура
- `cmd/api` - точка входа, graceful shutdown.
- `internal/config` - env-конфигурация.
- `internal/storage` - пул PostgreSQL.
- `internal/http` - маршруты и middleware.
- `internal/{company,news,knowledge,analysis}` - модели, сервисы, репозитории, handlers.
- `migrations` - схема БД.
