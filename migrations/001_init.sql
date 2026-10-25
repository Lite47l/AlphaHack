CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    industry TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS persons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS company_persons (
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (company_id, person_id)
);

CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS news (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (url)
);

CREATE TABLE IF NOT EXISTS company_news (
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    news_id UUID NOT NULL REFERENCES news(id) ON DELETE CASCADE,
    relevance_score NUMERIC(5,4),
    PRIMARY KEY (company_id, news_id)
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    institution TEXT NOT NULL DEFAULT '',
    document_url TEXT NOT NULL DEFAULT '',
    published_at TIMESTAMPTZ,
    file_hash TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analysis_results (
    analysis_id UUID PRIMARY KEY REFERENCES analyses(id) ON DELETE CASCADE,
    facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    bank_perspective JSONB NOT NULL DEFAULT '[]'::jsonb,
    ai_conclusions JSONB NOT NULL DEFAULT '[]'::jsonb,
    risks JSONB NOT NULL DEFAULT '[]'::jsonb,
    opportunities JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS analysis_sources (
    analysis_id UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    source_title TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (analysis_id, source_url)
);

CREATE INDEX IF NOT EXISTS idx_news_published_at ON news (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_company_news_news_id ON company_news (news_id);
CREATE INDEX IF NOT EXISTS idx_analyses_company_created ON analyses (company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses (status);
