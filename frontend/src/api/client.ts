// Единый API-клиент: базовый путь /api/v1, заголовки контекста, разбор {"error"}, таймауты, отмена.
import type {
  ChatHistory,
  ChatResponse,
  CompanyList,
  CompanyProfile,
  CreateInsightRequest,
  CreateInsightResponse,
  CreateNewsRequest,
  Feed,
  InsightEnvelope,
  MetricsSummary,
  News,
  RelevanceCompare,
  Role,
  SystemStatus,
  Trace,
} from './types';

export const API_BASE = '/api/v1';
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === '1' || import.meta.env.VITE_USE_MOCKS === 'true';
export const USER_ROLE: Role = 'cfo';

export class ApiError extends Error {
  status: number;
  kind: 'http' | 'timeout' | 'network' | 'aborted';
  constructor(message: string, status: number, kind: ApiError['kind'] = 'http') {
    super(message);
    this.status = status;
    this.kind = kind;
  }
}

export function isAbort(e: unknown): boolean {
  return (e instanceof ApiError && e.kind === 'aborted') || (e instanceof DOMException && e.name === 'AbortError');
}

let currentClientId: string | null = null;
/** Контекст по умолчанию для заголовка X-Client-Id (выбранный клиент). */
export function setClientContext(id: string | null) {
  currentClientId = id;
}

interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Явный X-Client-Id (иначе — выбранный клиент). */
  clientId?: string | null;
}

const DEFAULT_TIMEOUT = 20_000;

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v));
  }
  const headers: Record<string, string> = { Accept: 'application/json', 'X-User-Role': USER_ROLE };
  const cid = opts.clientId ?? currentClientId;
  if (cid) headers['X-Client-Id'] = cid;
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';

  // Отмена: внешний сигнал + таймаут
  const ctrl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    ctrl.abort();
  }, opts.timeoutMs ?? DEFAULT_TIMEOUT);
  const onAbort = () => ctrl.abort();
  if (opts.signal) {
    if (opts.signal.aborted) ctrl.abort();
    else opts.signal.addEventListener('abort', onAbort, { once: true });
  }

  try {
    if (USE_MOCKS) {
      const { mockRequest } = await import('../mocks/handler');
      const res = await Promise.race([
        mockRequest(method, path, params, opts.body, headers),
        new Promise<never>((_, rej) => ctrl.signal.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')), { once: true })),
      ]);
      if (res.status >= 400) {
        const msg = (res.data as { error?: string })?.error ?? `Ошибка ${res.status}`;
        throw new ApiError(msg, res.status);
      }
      return res.data as T;
    }

    const qs = params.toString();
    const resp = await fetch(`${API_BASE}${path}${qs ? `?${qs}` : ''}`, {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: ctrl.signal,
    });
    const text = await resp.text();
    let data: unknown = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }
    if (!resp.ok) {
      const msg =
        (data && typeof data === 'object' && 'error' in data && typeof (data as { error: unknown }).error === 'string'
          ? (data as { error: string }).error
          : null) ?? httpMessage(resp.status);
      throw new ApiError(msg, resp.status);
    }
    if (data === null && text) throw new ApiError('Сервер вернул некорректный JSON', resp.status);
    return data as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e instanceof DOMException && e.name === 'AbortError') || ctrl.signal.aborted) {
      if (timedOut) throw new ApiError('Сервер не ответил вовремя (таймаут)', 0, 'timeout');
      throw new ApiError('Запрос отменён', 0, 'aborted');
    }
    throw new ApiError('Нет соединения с сервером', 0, 'network');
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener('abort', onAbort);
  }
}

function httpMessage(status: number): string {
  if (status === 403) return 'Нет доступа в контексте выбранного клиента';
  if (status === 404) return 'Не найдено';
  if (status === 502 || status === 503 || status === 504) return 'Сервис временно недоступен';
  return `Ошибка сервера (${status})`;
}

const enc = encodeURIComponent;

export const api = {
  listCompanies: (query: string, signal?: AbortSignal, limit = 50) =>
    request<CompanyList>('GET', '/companies', { query: { query, limit, offset: 0 }, signal }),
  getCompany: (id: string, signal?: AbortSignal) =>
    request<CompanyProfile>('GET', `/companies/${enc(id)}`, { signal, clientId: id }),
  getFeed: (id: string, opts: { limit?: number; days?: number; includeFiltered?: boolean } = {}, signal?: AbortSignal) =>
    request<Feed>('GET', `/companies/${enc(id)}/feed`, {
      query: { limit: opts.limit ?? 20, days: opts.days, include_filtered: opts.includeFiltered ?? false },
      signal,
      clientId: id,
      timeoutMs: 30_000,
    }),
  getRelevance: (newsId: string, companyIds: string[], signal?: AbortSignal) =>
    request<RelevanceCompare>('GET', '/relevance', {
      query: { news_id: newsId, company_ids: companyIds.join(',') },
      signal,
      timeoutMs: 30_000,
    }),
  getNews: (id: string, signal?: AbortSignal) => request<News>('GET', `/news/${enc(id)}`, { signal }),
  createNews: (body: CreateNewsRequest, signal?: AbortSignal) =>
    request<News>('POST', '/news', { body, signal, timeoutMs: 30_000 }),
  createInsight: (body: CreateInsightRequest, signal?: AbortSignal) =>
    request<CreateInsightResponse>('POST', '/insights', { body, signal, clientId: body.company_id, timeoutMs: 30_000 }),
  getInsight: (id: string, clientId: string, signal?: AbortSignal) =>
    request<InsightEnvelope>('GET', `/insights/${enc(id)}`, { signal, clientId }),
  getTrace: (id: string, clientId: string, signal?: AbortSignal) =>
    request<Trace>('GET', `/insights/${enc(id)}/trace`, { signal, clientId }),
  getChat: (id: string, clientId: string, signal?: AbortSignal) =>
    request<ChatHistory>('GET', `/insights/${enc(id)}/chat`, { signal, clientId }),
  postChat: (id: string, clientId: string, question: string, signal?: AbortSignal) =>
    request<ChatResponse>('POST', `/insights/${enc(id)}/chat`, { body: { question }, signal, clientId, timeoutMs: 180_000 }),
  postFeedback: (id: string, clientId: string, rating: 1 | -1, reason = '') =>
    request<{ ok: boolean }>('POST', `/insights/${enc(id)}/feedback`, { body: { rating, reason }, clientId }),
  systemStatus: (signal?: AbortSignal) => request<SystemStatus>('GET', '/system/status', { signal }),
  metricsSummary: (signal?: AbortSignal) => request<MetricsSummary>('GET', '/metrics/summary', { signal }),
};
