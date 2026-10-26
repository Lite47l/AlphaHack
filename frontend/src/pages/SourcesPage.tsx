import { useEffect, useState } from 'react';
import { api, ApiError, isAbort } from '../api/client';
import type { KnowledgeItem } from '../api/types';
import { IconDoc, IconExternal } from '../components/Icons';
import { EmptyState, ErrorState, Skeleton } from '../components/ui';
import { fmtDate } from '../lib/format';

/** Реестр документов аналитики Альфа-Банка, на которые опирается раздел «Позиция банка». */
export function SourcesPage() {
  const [items, setItems] = useState<KnowledgeItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    setItems(null);
    setErr(null);
    const ctrl = new AbortController();
    api
      .knowledge(ctrl.signal)
      .then((r) => setItems([...r.items].sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at))))
      .catch((e) => !isAbort(e) && setErr(e instanceof ApiError ? e.message : 'Не удалось загрузить реестр документов'));
    return () => ctrl.abort();
  }, [nonce]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Источники</h1>
          <p className="page-sub">Аналитические материалы Альфа-Банка, на которые агент ссылается в разделе «Позиция Альфа-Банка»</p>
        </div>
      </div>
      <section className="panel">
        {err && <ErrorState title="Реестр недоступен" message={err} onRetry={() => setNonce((n) => n + 1)} />}
        {!err && !items && (
          <div className="stack">
            <Skeleton h={44} />
            <Skeleton h={44} />
            <Skeleton h={44} />
          </div>
        )}
        {items && items.length === 0 && <EmptyState title="Документов в реестре нет" />}
        {items && items.length > 0 && (
          <div className="doc-list">
            {items.map((d) => (
              <div className="doc-row" key={d.id}>
                <span className="doc-row__icon">
                  <IconDoc size={20} />
                </span>
                <div style={{ minWidth: 0 }}>
                  <div className="doc-row__title">{d.title}</div>
                  <div className="doc-row__meta">
                    {d.institution} · {fmtDate(d.published_at)}
                  </div>
                </div>
                {d.document_url && (
                  <a className="btn btn--secondary btn--sm" href={d.document_url} target="_blank" rel="noreferrer">
                    Открыть <IconExternal size={14} />
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      <p className="muted small">
        Новости берутся из открытых RSS-источников; у каждой новости в разборе указан первоисточник со ссылкой. Материалы 2021 года помечаются как устаревшие.
      </p>
    </div>
  );
}
