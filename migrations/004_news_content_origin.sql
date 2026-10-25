-- Полный текст, происхождение и время получения новости.
ALTER TABLE news ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '';
ALTER TABLE news ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'collector';
ALTER TABLE news ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE news SET fetched_at = created_at WHERE fetched_at > created_at;

CREATE INDEX IF NOT EXISTS idx_news_origin ON news (origin);
CREATE INDEX IF NOT EXISTS idx_news_fetched_at ON news (fetched_at DESC);

-- Existing base data is preserved during integration.
