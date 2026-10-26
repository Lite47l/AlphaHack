import { useEffect, useState } from 'react';
import { api, ApiError, isAbort, USER_ROLE } from '../api/client';
import type { InsightEnvelope } from '../api/types';

const POLL_MS = 1200;
const MAX_WAIT_MS = 240_000;

export type Phase = 'idle' | 'creating' | 'polling' | 'completed' | 'failed' | 'error';

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

/** enabled=false — ничего не запрашиваем (разбор запускается явным действием пользователя). */
export function useInsight(clientId: string | null, newsId: string | undefined, enabled = true) {
  const [state, setState] = useState<State>({ phase: enabled ? 'creating' : 'idle', env: null, insightId: null, cached: false, error: null });
  const [run, setRun] = useState<{ n: number; force: boolean }>({ n: 0, force: false });

  useEffect(() => {
    setState({ phase: enabled ? 'creating' : 'idle', env: null, insightId: null, cached: false, error: null });
    if (!enabled || !clientId || !newsId) return;
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
  }, [clientId, newsId, run, enabled]);

  return { ...state, retry: (force = false) => setRun((r) => ({ n: r.n + 1, force })) };
}

