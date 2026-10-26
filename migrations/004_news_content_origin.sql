-- Полный текст, происхождение и время получения новости.
ALTER TABLE news ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '';
ALTER TABLE news ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'collector';
ALTER TABLE news ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE news SET fetched_at = created_at WHERE fetched_at > created_at;

CREATE INDEX IF NOT EXISTS idx_news_origin ON news (origin);
CREATE INDEX IF NOT EXISTS idx_news_fetched_at ON news (fetched_at DESC);

-- Удаляем тестовые данные прежнего сида и mock-коллектора (на уже существующих volume).
DELETE FROM news
WHERE url IN ('https://example.com/prepared-news-1', 'https://example.com/prepared-news-2')
   OR url LIKE 'https://mock.invalid/%';
DELETE FROM sources WHERE name = 'Mock News Source';
DELETE FROM knowledge_documents
WHERE institution = 'Example Bank' AND document_url = 'https://bank.example.com/documents/test-1';
DELETE FROM companies WHERE name IN ('Alpha Test Company', 'Beta Test Company');
