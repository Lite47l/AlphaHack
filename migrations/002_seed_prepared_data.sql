INSERT INTO companies (name, industry, description)
SELECT seed.name, seed.industry, seed.description
FROM (VALUES
    ('Alpha Test Company', 'Technology', 'Демонстрационная компания для проверки API'),
    ('Beta Test Company', 'Finance', 'Демонстрационная финансовая компания')
) AS seed(name, industry, description)
WHERE NOT EXISTS (SELECT 1 FROM companies c WHERE c.name = seed.name);

INSERT INTO news(title, summary, url, published_at)
VALUES
    (
        'Первая тестовая новость',
        'Подготовленная новость для проверки ленты',
        'https://example.com/prepared-news-1',
        '2026-10-20T10:00:00Z'
    ),
    (
        'Вторая тестовая новость',
        'Подготовленная новость для проверки импорта',
        'https://example.com/prepared-news-2',
        '2026-10-21T10:00:00Z'
    )
ON CONFLICT (url) DO NOTHING;

INSERT INTO knowledge_documents (title, institution, document_url, published_at)
SELECT 'Тестовый документ банка', 'Example Bank', 'https://bank.example.com/documents/test-1',
       '2026-10-20T10:00:00Z'::timestamptz
WHERE NOT EXISTS (
    SELECT 1 FROM knowledge_documents WHERE document_url = 'https://bank.example.com/documents/test-1'
);
