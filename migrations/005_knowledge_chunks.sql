ALTER TABLE knowledge_documents
    ADD COLUMN IF NOT EXISTS file_hash TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_documents_file_hash
    ON knowledge_documents(file_hash)
    WHERE file_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, page_number, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_page
    ON knowledge_chunks(document_id, page_number);
