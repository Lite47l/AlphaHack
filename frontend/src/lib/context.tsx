import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, ApiError, isAbort, setClientContext } from '../api/client';
import type { CompanySummary, Feed } from '../api/types';

const LS_KEY = 'alfa-news.client';

/** Сколько событий запрашивается у ленты: если пришло столько же, событий может быть больше */
export const FEED_LIMIT = 30;

function lsGet(): string | null {
  try {
    return window.localStorage.getItem(LS_KEY);
  } catch {
    return null;
  }
}
function lsSet(v: string) {
  try {
    window.localStorage.setItem(LS_KEY, v);
  } catch {
    /* приватный режим / запрет хранилища — не критично */
  }
}

/* ---------------- выбранный клиент ---------------- */

interface ClientCtx {
  clientId: string | null;
  client: CompanySummary | null;
  companies: CompanySummary[];
  companiesTotal: number;
  dataSource: string | null;
  loading: boolean;
  error: string | null;
  setClient: (c: CompanySummary | string) => void;
  retry: () => void;
  /** Добавляет ?client= к внутренней ссылке */
  href: (path: string) => string;
}

const ClientContext = createContext<ClientCtx | null>(null);

export function ClientProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const urlClient = params.get('client');
  const [companies, setCompanies] = useState<CompanySummary[]>([]);
  const [total, setTotal] = useState(0);
  const [dataSource, setDataSource] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [extra, setExtra] = useState<Record<string, CompanySummary>>({});
  const [attempt, setAttempt] = useState(0);
  const fallbackId = useRef<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    api
      .listCompanies('', ctrl.signal)
      .then((r) => {
        setCompanies(r.items);
        setTotal(r.total);
        setDataSource(r.data_source);
        setLoading(false);
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setError(e instanceof ApiError ? e.message : 'Не удалось загрузить список компаний');
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [attempt]);

  // Выбор: URL → localStorage → первый из списка
  const clientId = useMemo(() => {
    if (urlClient) return urlClient;
    const saved = lsGet();
    if (saved) return saved;
    if (!fallbackId.current && companies[0]) fallbackId.current = companies[0].company_id;
    return fallbackId.current;
  }, [urlClient, companies]);

  setClientContext(clientId);

  // Держим ?client= в URL, чтобы ссылку можно было отправить
  useEffect(() => {
    if (clientId && urlClient !== clientId) {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.set('client', clientId);
          return p;
        },
        { replace: true },
      );
    }
    if (clientId) lsSet(clientId);
  }, [clientId, urlClient, setParams]);

  const client = useMemo(() => {
    if (!clientId) return null;
    return companies.find((c) => c.company_id === clientId) ?? extra[clientId] ?? null;
  }, [clientId, companies, extra]);

  // Клиент из URL может быть вне первой страницы списка — подгружаем его профиль
  useEffect(() => {
    if (!clientId || loading || client) return;
    const ctrl = new AbortController();
    api
      .getCompany(clientId, ctrl.signal)
      .then((p) => setExtra((x) => ({ ...x, [clientId]: p.summary })))
      .catch((e) => {
        if (isAbort(e)) return;
        if (e instanceof ApiError && e.status === 404 && companies[0]) {
          // неизвестный клиент → первый из списка
          setParams(
            (prev) => {
              const p = new URLSearchParams(prev);
              p.set('client', companies[0].company_id);
              return p;
            },
            { replace: true },
          );
        }
      });
    return () => ctrl.abort();
  }, [clientId, loading, client, companies, setParams]);

  const setClient = useCallback(
    (c: CompanySummary | string) => {
      const id = typeof c === 'string' ? c : c.company_id;
      if (typeof c !== 'string') setExtra((x) => ({ ...x, [id]: c }));
      lsSet(id);
      setParams((prev) => {
        const p = new URLSearchParams(prev);
        p.set('client', id);
        p.delete('event'); // выбранное событие принадлежало ленте прежней компании
        return p;
      });
    },
    [setParams],
  );

  const href = useCallback(
    (path: string) => {
      if (!clientId) return path;
      const [base, hash] = path.split('#');
      const sep = base.includes('?') ? '&' : '?';
      return `${base}${sep}client=${encodeURIComponent(clientId)}${hash ? `#${hash}` : ''}`;
    },
    [clientId],
  );

  const value: ClientCtx = {
    clientId,
    client,
    companies,
    companiesTotal: total,
    dataSource,
    loading,
    error,
    setClient,
    retry: () => setAttempt((a) => a + 1),
    href,
  };
  return <ClientContext.Provider value={value}>{children}</ClientContext.Provider>;
}

export function useClient(): ClientCtx {
  const v = useContext(ClientContext);
  if (!v) throw new Error('ClientProvider missing');
  return v;
}

/* ---------------- лента выбранного клиента ---------------- */

interface FeedCtx {
  feed: Feed | null;
  feedFor: string | null;
  loading: boolean;
  error: string | null;
  significant: number;
  reload: () => void;
}

const FeedContext = createContext<FeedCtx | null>(null);

export function FeedProvider({ children }: { children: ReactNode }) {
  const { clientId } = useClient();
  const [feed, setFeed] = useState<Feed | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    // при смене клиента — сразу очищаем старую ленту и отменяем запрос
    setFeed(null);
    setError(null);
    if (!clientId) return;
    const ctrl = new AbortController();
    setLoading(true);
    api
      .getFeed(clientId, { limit: FEED_LIMIT, includeFiltered: true }, ctrl.signal)
      .then((f) => {
        setFeed(f);
        setLoading(false);
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setError(e instanceof ApiError ? e.message : 'Не удалось загрузить ленту');
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [clientId, nonce]);

  const significant = useMemo(() => {
    if (!feed) return 0;
    if (typeof feed.stats?.significant === 'number') return feed.stats.significant;
    return feed.items.filter((i) => i.relevance.level === 'high' || i.relevance.level === 'medium').length;
  }, [feed]);

  return (
    <FeedContext.Provider
      value={{ feed, feedFor: feed?.company_id ?? null, loading, error, significant, reload: () => setNonce((n) => n + 1) }}
    >
      {children}
    </FeedContext.Provider>
  );
}

export function useFeed(): FeedCtx {
  const v = useContext(FeedContext);
  if (!v) throw new Error('FeedProvider missing');
  return v;
}
