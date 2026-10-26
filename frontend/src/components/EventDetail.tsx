import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, isAbort } from '../api/client';
import type { FeedItem, Source, SourceMap, Trace } from '../api/types';
import { useClient } from '../lib/context';
import { CONFIDENCE_LABEL, DIRECTION_LABEL, fmtDate, fmtDateTime, LEVEL_SHORT, SOURCE_PREFIX_LABEL, cls } from '../lib/format';
import { useInsight } from '../lib/useInsight';
import { AgentProgress, TraceView } from './agent';
import { ChatPanel } from './ChatPanel';
import { ComponentsTable } from './ComponentsTable';
import { eventIcon } from './eventIcon';
import {
  IconArrowLeft, IconArrowRight, IconBank, IconChart, IconChat, IconChevronRight, IconCompare, IconExternal, IconLink, IconList, IconSpark,
} from './Icons';
import { BankBody, StatementList } from './InsightView';
import { buildOrder, SourcePanel, SourceProvider, sourceTitle, type SourceRegistry } from './sources';
import { ErrorState, Notice, Spinner } from './ui';

function Block({
  icon,
  red,
  title,
  tag,
  children,
}: {
  icon: React.ReactNode;
  red?: boolean;
  title: string;
  tag?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="dblock">
      <span className={cls('dblock__icon', red && 'dblock__icon--red')}>{icon}</span>
      <div className="dblock__body">
        <div className="dblock__title">
          <h3>{title}</h3>
          {tag}
        </div>
        {children}
      </div>
    </section>
  );
}

function SourceLine({ id, s, n, onOpen }: { id: string; s: Source; n?: number; onOpen: (id: string) => void }) {
  const url = s.type === 'news' || s.type === 'bank' ? s.url : '';
  const sub =
    s.type === 'news'
      ? `${s.source_name} · ${fmtDate(s.published_at)}`
      : s.type === 'bank'
        ? `Аналитика Альфа-Банка${s.published_at ? ` · ${fmtDate(s.published_at)}` : ''}`
        : SOURCE_PREFIX_LABEL[id.split(':')[0]] ?? 'Источник';
  return (
    <div className="src-item">
      <span className="src-name">
        {n != null && <span className="muted">[{n}] </span>}
        {url ? (
          <a href={url} target="_blank" rel="noreferrer" title={sourceTitle(s)}>
            {sourceTitle(s)} <IconExternal size={12} />
          </a>
        ) : (
          <button type="button" className="src-link" onClick={() => onOpen(id)} title={sourceTitle(s)}>
            {sourceTitle(s)}
          </button>
        )}
      </span>
      <span className="src-sub">{sub}</span>
    </div>
  );
}

/** Подробности выбранного события. Разбор агентом запускается только явной кнопкой — выбор карточки ничего не генерирует. */
export function EventDetail({ item, filtered, onBack }: { item: FeedItem; filtered?: boolean; onBack: () => void }) {
  const { clientId, href } = useClient();
  const [started, setStarted] = useState(false);
  const ins = useInsight(clientId, item.news_id, started);
  const [chatSources, setChatSources] = useState<SourceMap>({});
  const [openSrc, setOpenSrc] = useState<string | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [traceErr, setTraceErr] = useState<string | null>(null);
  const [fullSummary, setFullSummary] = useState(false);

  const r = item.relevance;
  const result = ins.env?.result ?? null;
  const processing = ins.phase === 'creating' || ins.phase === 'polling';
  const allSources = useMemo<SourceMap>(() => ({ ...(result?.sources ?? {}), ...chatSources }), [result, chatSources]);

  useEffect(() => {
    if (!traceOpen || !ins.insightId || !clientId || ins.phase !== 'completed') return;
    const ctrl = new AbortController();
    setTraceErr(null);
    api
      .getTrace(ins.insightId, clientId, ctrl.signal)
      .then(setTrace)
      .catch((e) => !isAbort(e) && setTraceErr(e.message));
    return () => ctrl.abort();
  }, [traceOpen, ins.insightId, ins.phase, clientId]);

  const order = useMemo(() => {
    const ids: string[] = [];
    if (result) {
      const push = (xs: { source_ids: string[] }[]) => xs.forEach((s) => ids.push(...s.source_ids));
      push(result.what_happened);
      push(result.why_it_matters);
      push(result.bank_view.statements);
      push(result.ai_conclusions);
      push(result.risks);
      push(result.opportunities);
      push(result.actions);
      if (result.bank_offer) ids.push(...result.bank_offer.source_ids);
      ids.push(...Object.keys(result.sources));
    }
    ids.push(...Object.keys(chatSources));
    return buildOrder(ids);
  }, [result, chatSources]);

  const registry: SourceRegistry = useMemo(
    () => ({ number: (id) => order.get(id), get: (id) => allSources[id], open: (id) => setOpenSrc(id), activeId: openSrc }),
    [order, allSources, openSrc],
  );
  const addSources = useCallback((s: SourceMap) => setChatSources((prev) => ({ ...prev, ...s })), []);

  // список источников — только те, на которые опирается сам разбор; источники из ответов чата остаются доступны через маркеры
  const own = Object.entries(result?.sources ?? {}).sort((a, b) => (order.get(a[0]) ?? 999) - (order.get(b[0]) ?? 999));
  const newsSources = own.filter(([, s]) => s.type === 'news');
  const bankDocs = useMemo(() => {
    const m = new Map<string, { title: string; url: string; published_at: string; pages: number[]; firstId: string }>();
    for (const [id, s] of own) {
      if (s.type !== 'bank') continue;
      const cur = m.get(s.doc_id) ?? { title: s.doc_title, url: s.url, published_at: s.published_at, pages: [], firstId: id };
      if (s.page != null && !cur.pages.includes(s.page)) cur.pages.push(s.page);
      m.set(s.doc_id, cur);
    }
    return [...m.values()];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);
  const features = own.filter(([, s]) => s.type === 'profile' || s.type === 'graph');

  // «почему важно»: ответ агента, если он есть, иначе краткое объяснение из ленты; одинаковый текст не повторяем
  const reasons = r.reasons.filter((x) => x.trim() && x.trim() !== r.why_short.trim());
  const dir = item.event.direction && DIRECTION_LABEL[item.event.direction];

  return (
    <SourceProvider value={registry}>
      <div className="pane detail" aria-live="polite">
        <button className="btn btn--secondary btn--sm detail__back" onClick={onBack}>
          <IconArrowLeft size={14} /> Назад к событиям
        </button>

        <div className="detail__head">
          <div className="detail__thumb" aria-hidden="true">
            {eventIcon(item.event.event_type, 44)}
          </div>
          <div style={{ minWidth: 0 }}>
            <div className="detail__meta">
              {filtered ? <span className="tag tag--none">Не показана в ленте</span> : <span className={cls('tag', `tag--${r.level}`)}>{r.level === 'none' ? 'Не значимо' : `${LEVEL_SHORT[r.level]} значимость`}</span>}
              <span className="tag tag--fact">{item.event.event_label}</span>
              {dir && <span className="tag tag--fact">{dir}</span>}
              <span className="detail__date">{fmtDateTime(item.published_at)}</span>
            </div>
            <h2 className="detail__title">{item.title}</h2>
            <p className={cls('detail__summary', !fullSummary && 'is-clamped')}>{item.summary}</p>
            {item.summary.length > 260 && (
              <button className="link-btn" onClick={() => setFullSummary((v) => !v)} aria-expanded={fullSummary}>
                {fullSummary ? 'Свернуть' : 'Читать полностью'}
              </button>
            )}
            <div className="detail__links muted">
              <span>
                <span className="tag tag--fact">Факт из новости</span> {item.source_name}
              </span>
              {item.url && (
                <a className="link" href={item.url} target="_blank" rel="noreferrer">
                  Первоисточник <IconExternal size={13} />
                </a>
              )}
              <Link className="link" to={href(`/compare?news_id=${item.news_id}`)}>
                <IconCompare size={13} /> Сравнить для других клиентов
              </Link>
            </div>
          </div>
        </div>

        {item.duplicates.length > 0 && (
          <p className="muted small">
            Это же событие освещают: {[...new Set(item.duplicates.map((d) => d.source_name))].join(', ')}.
          </p>
        )}

        {r.profile_warnings.length > 0 && <Notice tone="warn">{r.profile_warnings.join('; ')}</Notice>}

        <Block icon={<IconChart size={20} />} title="Почему это важно" tag={<span className="tag tag--fact">Связь с профилем компании</span>}>
          {result && result.why_it_matters.length > 0 ? (
            <StatementList items={result.why_it_matters} features />
          ) : (
            <p className="dblock__text">{r.why_short}</p>
          )}
          {!(result && result.why_it_matters.length > 0) && reasons.length > 0 && (
            <ul className="reason-list">
              {reasons.slice(0, 3).map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          )}
          <details className="expander">
            <summary>На основании чего</summary>
            <div className="expander__body">
              <ComponentsTable relevance={r} />
            </div>
          </details>
        </Block>

        {/* до запуска разбора */}
        {ins.phase === 'idle' && (
          <div className="run-box">
            <div className="run-box__text">
              Разбор агентом покажет, что событие значит для компании, найдёт позицию Альфа-Банка и укажет источники.
              <span className="muted">Занимает 30–60 секунд; повторный запрос берётся из кэша.</span>
            </div>
            <button className="btn btn--primary" onClick={() => setStarted(true)}>
              <IconSpark size={16} /> Разобрать для компании
            </button>
          </div>
        )}

        {ins.phase === 'idle' && item.bank_coverage.found && (
          <Block icon={<IconBank size={20} />} red title="Позиция Альфа-Банка" tag={<span className="tag tag--bank">Аналитика Альфа-Банка</span>}>
            <p className="dblock__text">В аналитике банка есть материалы по теме события:</p>
            <ul className="reason-list">
              {item.bank_coverage.docs.map((d) => (
                <li key={d.doc_id}>{d.title}</li>
              ))}
            </ul>
            <p className="dblock__note">Цитата, страница и ссылка на документ появятся после разбора.</p>
          </Block>
        )}

        {processing && (
          <div style={{ marginTop: 12 }}>
            <AgentProgress steps={ins.env?.progress ?? []} status={ins.env?.status ?? 'queued'} newsTitle={item.title} />
          </div>
        )}

        {ins.phase === 'failed' && (
          <div style={{ marginTop: 12 }}>
            <ErrorState title="Агент не смог сформировать разбор" message={ins.error} onRetry={() => ins.retry(true)} />
          </div>
        )}
        {ins.phase === 'error' && (
          <div style={{ marginTop: 12 }}>
            <ErrorState title="Разбор недоступен" message={ins.error} onRetry={() => ins.retry(false)} />
          </div>
        )}

        {ins.phase === 'completed' && result && (
          <>
            {result.mode === 'rules' && (
              <div style={{ marginTop: 12 }}>
                <Notice tone="warn">Разбор сформирован правилами: LLM недоступна. Выводы шаблонные, источники указаны.</Notice>
              </div>
            )}

            <Block
              icon={<IconList size={20} />}
              title="Что это значит для компании"
              tag={<span className="tag tag--ai">Оценка ИИ, не установленный факт</span>}
            >
              {result.ai_conclusions.length > 0 && <StatementList items={result.ai_conclusions} />}
              {result.risks.length > 0 && (
                <>
                  <div className="sub-h">Риски</div>
                  <StatementList items={result.risks} />
                </>
              )}
              {result.opportunities.length > 0 && (
                <>
                  <div className="sub-h">Возможности</div>
                  <StatementList items={result.opportunities} />
                </>
              )}
              {result.ai_conclusions.length + result.risks.length + result.opportunities.length === 0 && (
                <p className="muted">Агент не сформировал выводов для этого события.</p>
              )}
              <div className="dblock__note">
                Общая уверенность: {CONFIDENCE_LABEL[result.confidence]}
                {result.limitations.length > 0 && ` · ${result.limitations[0]}`}
              </div>
            </Block>

            <Block
              icon={<IconBank size={20} />}
              red
              title="Позиция Альфа-Банка"
              tag={
                <>
                  <span className="tag tag--bank">Аналитика Альфа-Банка</span>
                  {result.bank_view.status === 'outdated' && <span className="tag tag--warn">материал устарел</span>}
                </>
              }
            >
              <div className="bank-pos">
                <BankBody bv={result.bank_view} />
              </div>
            </Block>

            {(result.actions.length > 0 || result.bank_offer) && (
              <Block icon={<IconChevronRight size={20} />} title="Что можно сделать" tag={<span className="tag tag--ai">Оценка ИИ</span>}>
                {result.actions.length > 0 && <StatementList items={result.actions} />}
                {result.bank_offer && (
                  <p className="dblock__text" style={{ marginTop: 8 }}>
                    <span className="tag tag--bank">Предложение банка</span> <strong>{result.bank_offer.product}</strong>: {result.bank_offer.text}
                  </p>
                )}
              </Block>
            )}

            <Block icon={<IconLink size={20} />} title="Источники">
              {newsSources.length + bankDocs.length > 0 ? (
                <div className="src-list">
                  {newsSources.map(([id, s]) => (
                    <SourceLine key={id} id={id} s={s} n={order.get(id)} onOpen={setOpenSrc} />
                  ))}
                  {bankDocs.map((d) => (
                    <div className="src-item" key={d.firstId}>
                      <span className="src-name">
                        {d.url ? (
                          <a href={d.url} target="_blank" rel="noreferrer" title={d.title}>
                            {d.title} <IconExternal size={12} />
                          </a>
                        ) : (
                          <button type="button" className="src-link" onClick={() => setOpenSrc(d.firstId)} title={d.title}>
                            {d.title}
                          </button>
                        )}
                      </span>
                      <span className="src-sub">
                        Аналитика Альфа-Банка{d.pages.length ? ` · стр. ${d.pages.sort((a, b) => a - b).join(', ')}` : ''}
                        {d.published_at ? ` · ${fmtDate(d.published_at)}` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">Источники не указаны.</p>
              )}
              {features.length > 0 && (
                <details className="expander">
                  <summary>Данные компании, на которые опирается разбор ({features.length})</summary>
                  <div className="expander__body src-list">
                    {features.map(([id, s]) => (
                      <SourceLine key={id} id={id} s={s} n={order.get(id)} onOpen={setOpenSrc} />
                    ))}
                  </div>
                </details>
              )}
              <details className="expander" onToggle={(e) => setTraceOpen((e.currentTarget as HTMLDetailsElement).open)}>
                <summary>Как получен вывод</summary>
                <div className="expander__body">
                  {traceErr && <ErrorState title="Трассировка недоступна" message={traceErr} />}
                  {!trace && !traceErr && (
                    <span className="muted">
                      <Spinner size={14} /> Загрузка трассировки…
                    </span>
                  )}
                  {trace && <TraceView trace={trace} />}
                </div>
              </details>
              <div className="dblock__note">
                Режим: {result.mode === 'llm' ? 'LLM-агент' : 'правила'} · проверка источников {result.validation?.passed ? 'пройдена' : 'не пройдена'}.{' '}
                <Link className="link" to={href(`/news/${item.news_id}`)}>
                  Полный разбор <IconArrowRight size={12} />
                </Link>
              </div>
            </Block>

            {clientId && (
              <details className="ask" open>
                <summary>
                  <IconChat size={18} /> Задайте вопрос по этой новости
                  <span className="ask__chev">
                    <IconChevronRight size={16} />
                  </span>
                </summary>
                <ChatPanel key={`${clientId}|${item.news_id}|${ins.insightId ?? ''}`} insightId={ins.insightId} clientId={clientId} ready onSources={addSources} embedded />
              </details>
            )}
          </>
        )}

        {ins.phase !== 'completed' && (
          <details className="ask" aria-disabled>
            <summary>
              <IconChat size={18} /> Задайте вопрос по этой новости
              <span className="ask__chev">
                <IconChevronRight size={16} />
              </span>
            </summary>
            <div className="chat__empty" style={{ padding: 16 }}>
              Вопросы доступны после разбора события: ответы опираются на его источники.
            </div>
          </details>
        )}

      </div>
      {openSrc && <SourcePanel id={openSrc} source={allSources[openSrc]} number={order.get(openSrc)} onClose={() => setOpenSrc(null)} />}
    </SourceProvider>
  );
}
