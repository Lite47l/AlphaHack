# MVP: knowledge PDF + RBC parser integration

## Что добавлено
- Локальный импорт PDF в `POST /api/v1/knowledge/collect`.
- Загрузка одного PDF через `POST /api/v1/knowledge/import` (multipart поле `file`).
- Извлечение текстового слоя по страницам и OCR только для страниц без текста.
- OCR 150 DPI/JPEG и `exec.CommandContext`, чтобы отмена контекста прекращала внешние процессы.
- SHA-256 для дедупликации PDF и сохранение чанков в PostgreSQL.
- RBC parser как отдельный контейнер и Go `RBCCollector`, подключённый к текущему `/api/v1/news/import`.

## Запуск
1. Распаковать архив.
2. Проверить, что `Russian_Trusted_Root_CA.cer` присутствует в корне (как и в исходном MVP).
3. Поместить PDF в `./data/knowledge`.
4. `docker compose up --build -d`
5. `docker compose logs -f backend rbc-parser`

## Endpoint-ы
- `GET /health`
- `GET /ready`
- `GET /api/v1/knowledge`
- `POST /api/v1/knowledge/collect` — локальные PDF
- `POST /api/v1/knowledge/import` — multipart PDF, поле `file`
- `POST /api/v1/news/import` — вызывает Alfa и RBC коллекторы

## Важно
- Это интеграционная заготовка, тесты Go и сборка Docker в этой среде не запускались.
- Для существующей базы миграции из `/docker-entrypoint-initdb.d` автоматически не применяются, если volume PostgreSQL уже создан. Примените `migrations/004_knowledge_chunks.sql` вручную к существующей базе.
- Парсер может быть тяжёлым: Natasha/модели загружаются при старте; первый запуск дольше из-за установки зависимостей. В текущем MVP импорт новостей синхронный; для production рекомендуется вынести его в фоновые задачи.
- Поля найденных компаний и ОКВЭД сейчас парсер отдаёт, но MVP-схема news их пока не хранит. Для этого нужна отдельная миграция и расширение News/repository.
- Для надёжности следует протестировать совместимость конкретных версий зависимостей и внешние сайты могут менять HTML/API.
