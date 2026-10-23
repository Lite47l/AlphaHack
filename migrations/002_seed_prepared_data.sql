INSERT INTO companies (name, industry, description)
VALUES
    (
    'Alpha Test Company',
     'Technology',
     'Демонстрационная компания для проверки API'
    ),
    (
     'Beta Test Company',
     'Finance',
     'Демонстрационная финансовая компания'
    )
ON CONFLICT DO NOTHING;

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

INSERT INTO knowledge_documents (
    title,
    institution,
    document_url,
    published_at
)
VALUES
    (
        'Тестовый документ банка',
        'Example Bank',
        'https://bank.example.com/documents/test-1',
        '2026-10-20T10:00:00Z'
    )
ON CONFLICT DO NOTHING;