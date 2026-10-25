import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api, ApiError, isAbort, USER_ROLE } from '../api/client';
import type { Insight, InsightEnvelope, News, SourceMap, Trace } from '../api/types';
import { AgentProgress, TraceView } from '../components/agent';
import { ChatPanel } from '../components/ChatPanel';
import { IconArrowLeft, IconCompare, IconExternal, IconRefresh } from '../components/Icons';
import { InsightView } from '../components/InsightView';
import { buildOrder, SourcePanel, SourceProvider, type SourceRegistry } from '../components/sources';
import { ErrorState, Notice, Skeleton, SkeletonCard, Spinner } from '../components/ui';
import { useClient, useFeed } from '../lib/context';
import { cls, fmtDateTime } from '../lib/format';

const POLL_MS = 1200;
const MAX_WAIT_MS = 240_000;

type Phase = 'creating' | 'polling' | 'completed' | 'failed' | 'error';

interface State {
  phase: Phase;
  env: InsightEnvelope | null;
  insightId: string | null;
  cached: boolean;
  error: string | null;
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((res, rej) => {
    const t = setTimeout(res, ms);
    signal.addEventListener('abort', () => {
      clearTimeout(t);
      rej(new DOMException('aborted', 'AbortError'));
    });
  });

function useInsight(clientId: string | null, newsId: string | undefined) {
  const [state, setState] = useState<State>({ phase: 'creating', env: null, insightId: null, cached: false, error: null });
  const [run, setRun] = useState<{ n: number; force: boolean }>({ n: 0, force: false });

  useEffect(() => {
    setState({ phase: 'creating', env: null, insightId: null, cached: false, error: null });
    if (!clientId || !newsId) return;
    const ctrl = new AbortController();
    const started = Date.now();
    (async () => {
      try {
        const created = await api.createInsight({ company_id: clientId, news_id: newsId, role: USER_ROLE, force: run.force || undefined }, ctrl.signal);
        setState((s) => ({ ...s, phase: 'polling', insightId: created.insight_id, cached: created.cached }));
        let failures = 0;
        for (;;) {
          let env: InsightEnvelope;
          try {
            env = await api.getInsight(created.insight_id, clientId, ctrl.signal);
            failures = 0;
          } catch (e) {
            if (isAbort(e)) throw e;
            // временные ошибки поллинга терпим, 403/404 — сразу ошибка
            if (e instanceof ApiError && (e.status === 403 || e.status === 404)) throw e;
            if (++failures >= 4) throw e;
            await sleep(POLL_MS * 2, ctrl.signal);
            continue;
          }
          if (env.status === 'completed') {
            setState((s) => ({ ...s, env, phase: env.result ? 'completed' : 'error', error: env.result ? null : 'Инсайт помечен готовым, но результат пуст' }));
            return;
          }
          if (env.status === 'failed') {
            setState((s) => ({ ...s, env, phase: 'failed', error: env.error ?? 'Агент завершился с ошибкой' }));
            return;
          }
          setState((s) => ({ ...s, env }));
          if (Date.now() - started > MAX_WAIT_MS) {
            throw new ApiError('Анализ занимает дольше обычного. Попробуйте обновить позже.', 0, 'timeout');
          }
          await sleep(POLL_MS, ctrl.signal);
        }
      } catch (e) {
        if (isAbort(e)) return;
        setState((s) => ({ ...s, phase: 'error', error: e instanceof ApiError ? e.message : 'Не удалось получить инсайт' }));
      }
    })();
    return () => ctrl.abort();
  }, [clientId, newsId, run]);

  return { ...state, retry: (force = false) => setRun((r) => ({ n: r.n + 1, force })) };
}

export function InsightPage() {
  const { newsId } = useParams();
  const { clientId, client, href } = useClient();
  const { feed } = useFeed();
  const ins = useInsight(clientId, newsId);
  const [news, setNews] = useState<News | null>(null);
  const [newsErr, setNewsErr] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [tab, setTab] = useState<'insight' | 'trace'>(params.get('tab') === 'trace' ? 'trace' : 'insight');
  const [trace, setTrace] = useState<Trace | null>(null);
  const [traceErr, setTraceErr] = useState<string | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceNonce, setTraceNonce] = useState(0);
  const [chatSources, setChatSources] = useState<SourceMap>({});
  const [openSrc, setOpenSrc] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<1 | -1 | null>(null);

  // сброс при смене клиента/новости
  useEffect(() => {
    setTrace(null);
    setTraceErr(null);
    setChatSources({});
    setOpenSrc(null);
    setFeedback(null);
  }, [clientId, newsId]);

  useEffect(() => {
    setNews(null);
    setNewsErr(null);
    if (!newsId) return;
    const ctrl = new AbortController();
    api
      .getNews(newsId, ctrl.signal)
      .then(setNews)
      .catch((e) => !isAbort(e) && setNewsErr(e.message));
    return () => ctrl.abort();
  }, [newsId]);

  // трассировка: при открытии вкладки и после завершения
  useEffect(() => {
    if (tab !== 'trace' || !ins.insightId || !clientId) return;
    const ctrl = new AbortController();
    setTraceLoading(true);
    setTraceErr(null);
    api
      .getTrace(ins.insightId, clientId, ctrl.signal)
      .then((t) => {
        setTrace(t);
        setTraceLoading(false);
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setTraceErr(e.message);
        setTraceLoading(false);
      });
    return () => ctrl.abort();
  }, [tab, ins.insightId, clientId, ins.phase, traceNonce]);

  const result: Insight | null = ins.env?.result ?? null;
  const allSources = useMemo<SourceMap>(() => ({ ...(result?.sources ?? {}), ...chatSources }), [result, chatSources]);

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
    trace?.steps.forEach((s) => ids.push(...(s.source_ids ?? [])));
    return buildOrder(ids);
  }, [result, chatSources, trace]);

  const registry: SourceRegistry = useMemo(
    () => ({
      number: (id) => order.get(id),
      get: (id) => allSources[id],
      open: (id) => setOpenSrc(id),
      activeId: openSrc,
    }),
    [order, allSources, openSrc],
  );

  const addSources = useCallback((s: SourceMap) => setChatSources((prev) => ({ ...prev, ...s })), []);

  const sendFeedback = (rating: 1 | -1) => {
    if (!ins.insightId || !clientId || feedback) return;
    setFeedback(rating);
    api.postFeedback(ins.insightId, clientId, rating).catch(() => setFeedback(null));
  };

  // GET /news/{id} обслуживает Go-шлюз; если он недоступен — берём метаданные из ленты или источника N: инсайта
  const fromFeed = feed ? [...feed.items, ...feed.filtered].find((i) => i.news_id === newsId) : undefined;
  const nSrc = result?.sources?.[`N:${newsId}`];
  const meta: Pick<News, 'title' | 'source_name' | 'published_at' | 'url' | 'summary'> | null =
    news ??
    (fromFeed
      ? fromFeed
      : nSrc && nSrc.type === 'news'
        ? { title: nSrc.title, source_name: nSrc.source_name, published_at: nSrc.published_at, url: nSrc.url, summary: nSrc.excerpt ?? '' }
        : null);
  const title = meta?.title ?? ins.env?.result?.what_happened?.[0]?.text;
  const processing = ins.phase === 'creating' || ins.phase === 'polling';

  return (
    <SourceProvider value={registry}>
      <div className="page page--wide">
        <div className="crumbs">
          <Link to={href('/news')} className="link">
            <IconArrowLeft size={14} /> Лента новостей
          </Link>
        </div>

        <div className="news-head card card--pad">
          <div className="news-head__main">
            <div className="muted small">
              {meta ? (
                <>
                  {meta.source_name} · {fmtDateTime(meta.published_at)}
                  {news?.origin === 'user' && <span className="chip chip--blue">добавлено пользователем</span>}
                </>
              ) : newsErr && !processing ? (
                <span>Метаданные новости недоступны: {newsErr}</span>
              ) : (
                <Skeleton h={12} w={200} />
              )}
            </div>
            <h1 className="news-head__title">{title ?? (newsErr && !processing ? `Новость ${newsId}` : <Skeleton h={26} w="70%" />)}</h1>
            {meta?.summary && <p className="news-head__summary">{meta.summary}</p>}
            <div className="muted small">
              Анализ для: <strong>{client?.display_name ?? clientId}</strong> · роль: финансовый директор
              {ins.cached && ins.phase === 'completed' && <span className="chip chip--neutral">из кэша</span>}
            </div>
          </div>
          <div className="news-head__actions">
            {meta?.url && (
              <a className="btn btn--secondary btn--sm" href={meta.url} target="_blank" rel="noreferrer">
                Первоисточник <IconExternal size={14} />
              </a>
            )}
            <Link className="btn btn--secondary btn--sm" to={href(`/compare?news_id=${newsId}`)}>
              <IconCompare size={14} /> Сравнить для других клиентов
            </Link>
            <button className="btn btn--ghost btn--sm" onClick={() => ins.retry(true)} disabled={processing} title="Пересчитать без кэша">
              <IconRefresh size={14} /> Пересчитать
            </button>
          </div>
        </div>

        <div className="tabs">
          <button className={cls('tab', tab === 'insight' && 'is-active')} onClick={() => setTab('insight')}>
            Инсайт
          </button>
          <button className={cls('tab', tab === 'trace' && 'is-active')} onClick={() => setTab('trace')} disabled={!ins.insightId}>
            Трассировка агента
          </button>
        </div>

        <div className="insight-layout">
          <div className="insight-layout__main">
            {tab === 'insight' && (
              <>
                {ins.phase === 'creating' && (
                  <>
                    <AgentProgress steps={[]} status="queued" newsTitle={meta?.title} />
                    <SkeletonCard lines={4} />
                  </>
                )}
                {ins.phase === 'polling' && ins.env && <AgentProgress steps={ins.env.progress} status={ins.env.status} newsTitle={meta?.title} />}
                {ins.phase === 'polling' && !ins.env && <AgentProgress steps={[]} status="queued" newsTitle={meta?.title} />}
                {ins.phase === 'failed' && (
                  <>
                    <ErrorState title="Агент не смог сформировать инсайт" message={ins.error} onRetry={() => ins.retry(true)} />
                    {ins.env && ins.env.progress.length > 0 && <AgentProgress steps={ins.env.progress} status="failed" />}
                  </>
                )}
                {ins.phase === 'error' && <ErrorState title="Инсайт недоступен" message={ins.error} onRetry={() => ins.retry(false)} />}
                {ins.phase === 'completed' && result && (
                  <>
                    <InsightView insight={result} />
                    <div className="feedback">
                      <span className="muted small">Инсайт был полезен?</span>
                      <button className={cls('btn btn--secondary btn--sm', feedback === 1 && 'is-on')} onClick={() => sendFeedback(1)} disabled={!!feedback}>
                        Да, полезно
                      </button>
                      <button className={cls('btn btn--secondary btn--sm', feedback === -1 && 'is-on')} onClick={() => sendFeedback(-1)} disabled={!!feedback}>
                        Нет
                      </button>
                      {feedback && <span className="muted small">Спасибо, оценка сохранена</span>}
                    </div>
                  </>
                )}
              </>
            )}
            {tab === 'trace' && (
              <>
                {processing && <Notice>Агент ещё работает — трассировка неполная, обновится по завершении.</Notice>}
                {traceLoading && !trace && (
                  <div className="card card--pad">
                    <Spinner /> Загрузка трассировки…
                  </div>
                )}
                {traceErr && <ErrorState title="Трассировка недоступна" message={traceErr} onRetry={() => setTraceNonce((n) => n + 1)} />}
                {trace && <TraceView trace={trace} />}
              </>
            )}
          </div>
          <div className="insight-layout__side">
            {clientId && (
              <ChatPanel
                key={`${clientId}|${newsId}|${ins.insightId ?? ''}`}
                insightId={ins.insightId}
                clientId={clientId}
                ready={ins.phase === 'completed'}
                onSources={addSources}
              />
            )}
          </div>
        </div>
      </div>
      {openSrc && <SourcePanel id={openSrc} source={allSources[openSrc]} number={order.get(openSrc)} onClose={() => setOpenSrc(null)} />}
    </SourceProvider>
  );
}
