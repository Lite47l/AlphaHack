import { useEffect, useState } from 'react';
import { api, ApiError, isAbort } from '../api/client';
import type { MetricsSummary, SystemStatus } from '../api/types';
import { IconRefresh } from '../components/Icons';
import { Chip, ErrorState, SectionTitle, SkeletonCard } from '../components/ui';
import { fmtMs, fmtNum, fmtPct } from '../lib/format';

// Подписи для известных ключей; неизвестные показываются как есть (структура может расширяться).
const LABELS: Record<string, string> = {
  insights_total: 'Инсайтов всего',
  insights_24h: 'Инсайтов за сутки',
  validation_pass_rate: 'Прошли валидацию',
  bank_view_found_rate: 'Найдена позиция банка',
  avg_latency_ms: 'Средняя задержка',
  p95_latency_ms: 'Задержка p95',
  tokens_24h: 'Токены за сутки',
  mode_share: 'Доля режимов',
  feedback: 'Оценки пользователей',
  chat_messages_24h: 'Сообщений в чате за сутки',
  feed_requests_24h: 'Запросов ленты за сутки',
  data_source: 'Источник данных',
  profiles: 'Профилей компаний',
  profiles_version: 'Версия профилей',
  corpus_version: 'Версия корпуса банка',
  news_in_db: 'Новостей в базе',
  llm: 'LLM',
  llm_enabled: 'LLM включена',
  mode: 'Режим',
  prompt: 'вход',
  completion: 'выход',
  positive: 'полезно',
  negative: 'не полезно',
  rules: 'правила',
  note: 'Примечание',
  by_status: 'По статусам',
  by_mode: 'По режимам',
  completed: 'готово',
  failed: 'ошибка',
  processing: 'в работе',
  queued: 'в очереди',
  avg_duration_ms: 'Среднее время инсайта',
  avg_chat_duration_ms: 'Среднее время ответа чата',
  avg_repairs: 'Доработок на инсайт',
  chat_messages: 'Сообщений в чате',
  up: 'полезно',
  down: 'не полезно',
  llm_tokens_today: 'Токены LLM сегодня',
  llm_calls_today: 'Вызовы LLM сегодня',
  cache_entries: 'Записей в кэше',
  segment_min_revenue: 'Порог выручки сегмента, ₽',
  bank_documents: 'Документов аналитики банка',
  bank_fragments: 'Фрагментов аналитики',
  llm_budget_left_today: 'Остаток бюджета токенов',
  prompt_version: 'Версия промпта',
  llm_base_url_set: 'Адрес LLM задан',
  models: 'Модели',
  models_allowed: 'Модели разрешены',
  daily_token_budget: 'Суточный бюджет токенов',
  agent_limits: 'Лимиты агента',
  max_steps: 'шагов, макс.',
  max_seconds: 'секунд, макс.',
  max_repairs: 'доработок, макс.',
  planner: 'планировщик',
  extractor: 'извлечение',
  writer: 'автор',
  chat: 'чат',
};

const label = (k: string) => LABELS[k] ?? k.replace(/_/g, ' ');

function fmtScalar(k: string, v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'да' : 'нет';
  if (typeof v === 'number') {
    if (/_ms$|latency/.test(k)) return fmtMs(v);
    if (/(^|_)(rate|share|ratio|pct)(_|$)/.test(k)) return fmtPct(v, 1);
    if (/avg_|budget|tokens|count|total|calls|entries|messages/.test(k)) return v.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
    if (v > 0 && v < 1 && !Number.isInteger(v)) return fmtPct(v, 1);
    return fmtNum(v);
  }
  if (typeof v === 'string') {
    if (k === 'mode') return v === 'llm' ? 'LLM-агент' : v === 'rules' ? 'Правила (LLM недоступна)' : v;
    if (k === 'data_source') return v === 'real' ? 'реальные данные' : v === 'synthetic' ? 'синтетические данные' : v;
    return v;
  }
  return JSON.stringify(v);
}

function Value({ k, v }: { k: string; v: unknown }) {
  if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
    const entries = Object.entries(v as Record<string, unknown>);
    // доли (сумма ≈ 1) — как полосы
    const nums = entries.filter(([, x]) => typeof x === 'number') as Array<[string, number]>;
    const sum = nums.reduce((a, [, x]) => a + x, 0);
    if (nums.length === entries.length && nums.length > 1 && Math.abs(sum - 1) < 0.02) {
      return (
        <div className="bars">
          {nums.map(([kk, x]) => (
            <div className="bar" key={kk}>
              <span className="bar__label">{label(kk)}</span>
              <span className="bar__track">
                <span style={{ width: `${x * 100}%` }} />
              </span>
              <span className="bar__val">{fmtPct(x)}</span>
            </div>
          ))}
        </div>
      );
    }
    return (
      <dl className="kv kv--compact">
        {entries.map(([kk, x]) => (
          <div key={kk} className="kv__row">
            <dt>{label(kk)}</dt>
            <dd>{x !== null && typeof x === 'object' ? <Value k={kk} v={x} /> : fmtScalar(kk, x)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x !== 'object' || x === null)) return <span>{v.map((x) => fmtScalar(k, x)).join(', ') || '—'}</span>;
    return <pre className="json">{JSON.stringify(v, null, 2)}</pre>;
  }
  return <span>{fmtScalar(k, v)}</span>;
}

function Panel({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);
  const scalars = entries.filter(([, v]) => v === null || typeof v !== 'object');
  const objects = entries.filter(([, v]) => v !== null && typeof v === 'object');
  return (
    <>
      <div className="kpis kpis--auto">
        {scalars.map(([k, v]) => (
          <div key={k} className="kpi">
            <div className="kpi__label">{label(k)}</div>
            <div className={k === 'note' ? 'kpi__text' : 'kpi__value'}>{fmtScalar(k, v)}</div>
          </div>
        ))}
      </div>
      {objects.length > 0 && (
        <div className="grid-3">
          {objects.map(([k, v]) => (
            <div key={k} className="card card--pad">
              <div className="kpi__label">{label(k)}</div>
              <Value k={k} v={v} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export function MonitoringPage() {
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [mErr, setMErr] = useState<string | null>(null);
  const [sErr, setSErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setMErr(null);
    setSErr(null);
    api
      .metricsSummary(ctrl.signal)
      .then(setMetrics)
      .catch((e) => !isAbort(e) && setMErr(e instanceof ApiError ? e.message : 'Ошибка'));
    api
      .systemStatus(ctrl.signal)
      .then(setStatus)
      .catch((e) => !isAbort(e) && setSErr(e instanceof ApiError ? e.message : 'Ошибка'));
    return () => ctrl.abort();
  }, [nonce]);

  return (
    <div className="page page--wide">
      <div className="page-head">
        <div>
          <h1>Мониторинг качества</h1>
          <p className="muted">Состояние сервиса и метрики качества инсайтов.</p>
        </div>
        <button className="btn btn--secondary btn--sm" onClick={() => setNonce((n) => n + 1)}>
          <IconRefresh size={14} /> Обновить
        </button>
      </div>

      <SectionTitle
        aside={
          status && (
            <Chip tone={status.mode === 'llm' ? 'green' : 'amber'}>{status.mode === 'llm' ? 'LLM доступна' : 'режим правил — LLM недоступна'}</Chip>
          )
        }
      >
        Состояние системы
      </SectionTitle>
      {sErr && <ErrorState message={sErr} onRetry={() => setNonce((n) => n + 1)} />}
      {!sErr && !status && <SkeletonCard lines={3} />}
      {status && <Panel data={status as Record<string, unknown>} />}

      <SectionTitle>Метрики качества</SectionTitle>
      {mErr && <ErrorState message={mErr} onRetry={() => setNonce((n) => n + 1)} />}
      {!mErr && !metrics && <SkeletonCard lines={3} />}
      {metrics && <Panel data={metrics} />}
    </div>
  );
}
