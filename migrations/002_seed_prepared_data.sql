-- Реестр аналитических документов Альфа-Банка (data/bank_corpus/corpus.json, поле documents).
-- doc_key = doc_id из корпуса; вставка идемпотентна.
ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS doc_key TEXT UNIQUE;

INSERT INTO knowledge_documents (doc_key, title, institution, document_url, published_at)
VALUES
    ('alfa-key-rate-2026-09-11', 'Ключевая ставка ЦБ РФ: ставка без изменения на 14,0%, риторика стала жестче', 'Альфа-Банк', 'https://drive.google.com/file/d/1shHG89LtMgHT1_uEebHmQSFZe_zbeq7-/view', '2026-09-11T00:00:00+03:00'),
    ('alfa-inflation-2026-09-02', 'Инфляция 25–31 августа: основные выводы', 'Альфа-Банк', 'https://drive.google.com/file/d/19iW3Ph8_wO0HHQY7Ik4lTfC3jRc9gjWV/view', '2026-09-02T00:00:00+03:00'),
    ('alfa-macrostat-7m26-2026-09-07', 'Макростатистика 7М26: данные по рынку труда не подтверждают охлаждения экономики', 'Альфа-Банк', 'https://drive.google.com/file/d/1HZDq3WGRFdzgm1TZ5hWL23Q3I9c2Eq64/view', '2026-09-07T00:00:00+03:00'),
    ('alfa-macrostat-1h26-2026-07-31', 'Макростатистика 1П26: слабый рост 1П26 смещает прогноз роста ВВП на 0,1% за год', 'Альфа-Банк', 'https://drive.google.com/file/d/1khcHwoS0FkG9p_0J4XoHGaGq3B4V0ime/view', '2026-07-31T00:00:00+03:00'),
    ('alfa-consumption-2026-08-05', 'Потребление на пике', 'Альфа-Банк', 'https://drive.google.com/file/d/1riR1lhsb6EY1MwGMxdBlS_tI5ed9mIiz/view', '2026-08-05T00:00:00+03:00'),
    ('alfa-fi-strategy-3q26-2026-07-22', 'Тактический взгляд на 3-й квартал 2026 года: время собирать камни', 'Альфа-Банк', 'https://drive.google.com/file/d/1hq3Fhyz9ce_sRyGUQB1MdoHeQdfAJfhK/view', '2026-07-22T00:00:00+03:00'),
    ('alfa-bond-brief-2026-09-14', 'Бонд Бриф: итоги недели', 'Альфа-Банк', 'https://drive.google.com/file/d/1bPzix_332N2CyMY0tqCHuYtGsfJWnFGv/view', '2026-09-14T00:00:00+03:00'),
    ('alfa-gold-digest-2026-08', 'Обзор рынка золота, август 2026', 'Альфа-Банк', 'https://drive.google.com/file/d/1a7TXOCHARfKzUR0hn9Cm9gQSrIldxTDE/view', '2026-09-01T00:00:00+03:00'),
    ('alfa-russian-steel-2021-04-15', 'Commodities performance: Российская сталь — ралли цен продолжается (прогноз за 1К21)', 'Альфа-Банк', 'https://drive.google.com/file/d/1yLCBrIoyIsubLTEBvBHh6io48ysnW-wn/view', '2021-04-15T00:00:00+03:00')
ON CONFLICT (doc_key) DO NOTHING;
