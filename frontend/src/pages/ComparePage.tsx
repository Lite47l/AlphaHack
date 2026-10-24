import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, ApiError, isAbort } from '../api/client';
import type { CompanySummary, RelevanceCompare } from '../api/types';
import { IconArrowRight, IconCheck, IconExternal } from '../components/Icons';
import { Chip, EmptyState, ErrorState, LevelBadge, ScoreBar, SkeletonCard } from '../components/ui';
import { useClient, useFeed } from '../lib/context';
import { cls, CONFIDENCE_LABEL, fmtBn, fmtDateTime } from '../lib/format';

const MAX = 3;

/** Подбирает по умолчанию компании из разных отраслей — так контраст значимости нагляднее. */
function defaults(companies: CompanySummary[], current: string | null): string[] {
  const res: string[] = current ? [current] : [];
  const used = new Set(companies.find((c) => c.company_id === current)?.sectors.map((s) => s.key) ?? []);
  for (const c of companies) {
    if (res.length >= MAX) break;
    if (res.includes(c.company_id)) continue;
    const k = c.sectors[0]?.key;
    if (k && used.has(k)) continue;
    res.push(c.company_id);
    if (k) used.add(k);
  }
  for (const c of companies) {
    if (res.length >= MAX) break;
    if (!res.includes(c.company_id)) res.push(c.company_id);
  }
  return res;
}

export function ComparePage() {
  const { companies, clientId, href } = useClient();
  const { feed } = useFeed();
  const [params, setParams] = useSearchParams();
  const newsId = params.get('news_id');
  const idsParam = params.get('ids');
  const [data, setData] = useState<RelevanceCompare | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [known, setKnown] = useState<Record<string, CompanySummary>>({});
  const [found, setFound] = useState<CompanySummary[] | null>(null);

  // поиск по всем компаниям на сервере (GET /companies?query=)
  useEffect(() => {
    if (!filter.trim()) {
      setFound(null);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      api
        .listCompanies(filter.trim(), ctrl.signal)
        .then((r) => setFound(r.items))
        .catch(() => undefined);
    }, 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [filter]);

  const selected = useMemo(() => {
    if (idsParam) return idsParam.split(',').filter(Boolean).slice(0, MAX);
    return defaults(companies, clientId);
  }, [idsParam, companies, clientId]);

  const update = (key: string, value: string | null) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (value) p.set(key, value);
        else p.delete(key);
        return p;
      },
      { replace: true },
    );

  const toggle = (id: string) => {
    const has = selected.includes(id);
    const next = has ? selected.filter((x) => x !== id) : selected.length >= MAX ? selected : [...selected, id];
    update('ids', next.join(','));
  };

  useEffect(() => {
    setData(null);
    setErr(null);
    if (!newsId || selected.length < 2) return;
    const ctrl = new AbortController();
    setLoading(true);
    api
      .getRelevance(newsId, selected, ctrl.signal)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setErr(e instanceof ApiError ? e.message : 'Ошибка');
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [newsId, selected.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  // выбранные компании могут быть вне первой страницы списка — подгружаем их карточки
  useEffect(() => {
    const missing = selected.filter((id) => !companies.some((c) => c.company_id === id) && !known[id]);
    if (!missing.length) return;
    const ctrl = new AbortController();
    missing.forEach((id) =>
      api
        .getCompany(id, ctrl.signal)
        .then((p) => setKnown((k) => ({ ...k, [id]: p.summary })))
        .catch(() => undefined),
    );
    return () => ctrl.abort();
  }, [selected.join(','), companies]); // eslint-disable-line react-hooks/exhaustive-deps

  const results = useMemo(
    () => (data ? [...data.results].sort((a, b) => b.relevance.score - a.relevance.score) : []),
    [data],
  );
  const pinned: CompanySummary[] = selected.map(
    (id) =>
      companies.find((c) => c.company_id === id) ??
      known[id] ?? {
        company_id: id, display_name: `Компания ${id}`, subtitle: 'загрузка…', okved_code: null, region: null, revenue: null, cl_type: null,
        sectors: [], profile_status: 'matched', completeness: 'complete', key_missing: [], top_channels: [],
      },
  );
  const shown = [
    ...pinned,
    ...(found ?? companies).filter((c) => !selected.includes(c.company_id)),
  ];

  return (
    <div className="page page--wide">
      <div className="page-head">
        <div>
          <h1>Сравнение значимости</h1>
          <p className="muted">Одна и та же новость по-разному значима для разных компаний — видно, из чего складывается оценка.</p>
        </div>
      </div>

      <div className="card card--pad compare-pick">
        <label className="field">
          <span>Новость</span>
          <select value={newsId ?? ''} onChange={(e) => update('news_id', e.target.value || null)}>
            <option value="">— выберите новость из ленты клиента —</option>
            {newsId && !feed?.items.some((i) => i.news_id === newsId) && <option value={newsId}>{data?.news.title ?? `Новость ${newsId}`}</option>}
            {feed?.items.map((i) => (
              <option key={i.news_id} value={i.news_id}>
                {i.title}
              </option>
            ))}
          </select>
        </label>
        <div className="field">
          <span>
            Компании ({selected.length} из {MAX}, минимум 2)
          </span>
          <input placeholder="Фильтр по ID, отрасли, региону" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <div className="pick-list">
            {shown.map((c) => {
              const on = selected.includes(c.company_id);
              return (
                <button
                  key={c.company_id}
                  className={cls('pick', on && 'is-on')}
                  onClick={() => {
                    if (!companies.some((x) => x.company_id === c.company_id)) setKnown((k) => ({ ...k, [c.company_id]: c }));
                    toggle(c.company_id);
                  }}
                  disabled={!on && selected.length >= MAX}
                >
                  <span className="pick__box">{on && <IconCheck size={12} />}</span>
                  <span className="pick__text">
                    <span className="strong">{c.display_name}</span>
                    {c.company_id === clientId && <Chip tone="red">текущий клиент</Chip>}
                    <span className="muted small">
                      {c.subtitle} · {c.region ?? 'регион не указан'} · {fmtBn(c.revenue)}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {!newsId && <EmptyState title="Выберите новость" text="Или откройте сравнение со страницы инсайта кнопкой «Сравнить для других клиентов»." />}
      {newsId && selected.length < 2 && <EmptyState title="Выберите минимум две компании" />}
      {err && <ErrorState message={err} />}
      {loading && (
        <div className="grid-3">
          <SkeletonCard lines={5} />
          <SkeletonCard lines={5} />
          <SkeletonCard lines={5} />
        </div>
      )}
      {data && (
        <>
          <div className="card card--pad compare-news">
            <div className="muted small">
              {data.news.source_name} · {fmtDateTime(data.news.published_at)} · <Chip tone="dark">{data.event.event_label}</Chip>
            </div>
            <h2>{data.news.title}</h2>
            {data.news.url && (
              <a href={data.news.url} target="_blank" rel="noreferrer" className="link small">
                первоисточник <IconExternal size={12} />
              </a>
            )}
          </div>
          <div className={cls('compare-cols', `compare-cols--${results.length}`)}>
            {results.map((r, idx) => (
              <div key={r.company_id} className={cls('card', 'compare-col', `compare-col--${r.relevance.level}`)}>
                <div className="compare-col__rank">#{idx + 1}</div>
                <div className="strong">{r.display_name}</div>
                <div className="muted small compare-col__sub">{r.subtitle}</div>
                <div className="compare-col__score">
                  <span className="compare-col__num">{r.relevance.score.toFixed(2)}</span>
                  <LevelBadge level={r.relevance.level} />
                </div>
                <ScoreBar score={r.relevance.score} level={r.relevance.level} wide />
                <div className="feed-card__why">
                  <span className="why-label">Почему</span>
                  <span>{r.relevance.why_short}</span>
                </div>
                {r.relevance.components.length > 0 && (
                  <div className="mini-comps">
                    {r.relevance.components.map((c) => (
                      <div key={c.key} className={cls('mini-comp', c.contribution <= 0 && 'is-zero')} title={c.reason}>
                        <span className="mini-comp__label">{c.label}</span>
                        <span className="mini-comp__bar">
                          <span style={{ width: `${(c.contribution / Math.max(c.weight, 0.0001)) * 100}%` }} />
                        </span>
                        <span className="mini-comp__val">+{c.contribution.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                )}
                {r.relevance.reasons.length > 0 && (
                  <ul className="plain-list small">
                    {r.relevance.reasons.map((x, i) => (
                      <li key={i}>{x}</li>
                    ))}
                  </ul>
                )}
                {r.relevance.profile_warnings.length > 0 && (
                  <div className="feed-card__warn small">{r.relevance.profile_warnings.join('; ')}</div>
                )}
                <div className="muted small">уверенность: {CONFIDENCE_LABEL[r.relevance.confidence]}</div>
                {newsId && r.company_id === clientId && (
                  <Link to={href(`/news/${newsId}`)} className="btn btn--primary btn--sm">
                    Инсайт для текущего клиента <IconArrowRight size={14} />
                  </Link>
                )}
                {newsId && r.company_id !== clientId && (
                  <Link to={`/news/${newsId}?client=${encodeURIComponent(r.company_id)}`} className="btn btn--secondary btn--sm">
                    Переключиться и открыть инсайт <IconArrowRight size={14} />
                  </Link>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
