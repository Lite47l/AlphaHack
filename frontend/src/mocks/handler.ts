// МОК-СЕРВЕР: эмулирует API по docs/api_contract.md в памяти браузера.
// Подключается только при VITE_USE_MOCKS=1 (см. src/api/client.ts).
import companiesJson from './companies.json';
import { MOCK_CHUNKS, MOCK_DUPLICATES, MOCK_NEWS, type MockNews } from './news';
import type {
  ChatMessage,
  CompanyList,
  CompanyProfile,
  CreateInsightResponse,
  Feed,
  FeedItem,
  Insight,
  InsightEnvelope,
  ProgressStep,
  Relevance,
  RelevanceComponent,
  Source,
  SourceMap,
  Statement,
  Trace,
  TraceStep,
} from '../api/types';

export interface MockResponse {
  status: number;
  data: unknown;
}

const PROFILES = companiesJson as unknown as CompanyProfile[];
const NEWS: MockNews[] = [...MOCK_NEWS];

const WEIGHTS = { sector: 0.27, channel: 0.3, counterparty: 0.12, region: 0.08, macro: 0.15, bank: 0.08 };
const LABELS: Record<string, string> = {
  sector: 'Отрасль компании',
  channel: 'Каналы влияния на компанию',
  counterparty: 'Контрагенты (граф платежей)',
  region: 'Регион регистрации',
  macro: 'Макрозначимость события',
  bank: 'Есть позиция в аналитике банка',
};
const FIELD_LABEL: Record<string, string> = {
  REGION: 'региона',
  MAINOKVED_CODE: 'ОКВЭД',
  CL_PRODUCT_LOA_MARK: 'признака кредитов',
  AMOUNT_WORKERS_FNS_GRADATION: 'численности',
  REVENUE_COMPANY: 'выручки',
};

const r2 = (x: number) => Math.round(x * 1000) / 1000;
const nowIso = () => new Date().toISOString();
const uuid = () =>
  'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });

function profile(id: string) {
  return PROFILES.find((p) => p.summary.company_id === id);
}

/* ---------------- ранжирование (упрощённая копия ai/app/ranking.py) ---------------- */

function relevanceFor(p: CompanyProfile, n: MockNews): Relevance {
  const warnings = p.summary.key_missing.map((f) => `Неполный профиль: нет ${FIELD_LABEL[f] ?? f}`);
  if (!n.business) {
    return {
      score: 0,
      level: 'none',
      components: [],
      reasons: ['Публикация не относится к бизнес-событиям'],
      why_short: 'Не относится к бизнесу',
      confidence: 'high',
      profile_warnings: [],
    };
  }
  const comps: RelevanceComponent[] = [];
  const add = (key: keyof typeof WEIGHTS, value: number, reason: string, evidence: string[]) =>
    comps.push({
      key,
      label: LABELS[key],
      value: r2(value),
      weight: WEIGHTS[key],
      contribution: r2(value * WEIGHTS[key]),
      reason,
      evidence,
    });

  const cs = p.summary.sectors.map((s) => s.key);
  const matched = n.event.sectors.filter((s) => cs.includes(s));
  const sectorLabels = matched.map((s) => p.summary.sectors.find((x) => x.key === s)?.label ?? s);
  add(
    'sector',
    matched.length ? (matched[0] === cs[0] || matched.length > 1 ? 1 : 0.75) : 0,
    matched.length ? `Событие касается отрасли компании: ${sectorLabels.join(', ')}` : 'Отрасль события не совпадает с ОКВЭД компании',
    matched.length ? ['P:MAINOKVED_CODE'] : [],
  );

  const hits = Object.entries(n.channels)
    .map(([k, w]) => {
      const c = p.channels.find((x) => x.key === k);
      return c ? { v: w * c.strength, c } : null;
    })
    .filter((x): x is NonNullable<typeof x> => !!x)
    .sort((a, b) => b.v - a.v);
  const chV = hits.length ? Math.min(1, hits[0].v + (hits[1] ? 0.15 * hits[1].v : 0)) : 0;
  add(
    'channel',
    chV,
    hits.length ? `${hits[0].c.label}: ${hits[0].c.notes[0]?.toLowerCase() ?? ''}` : 'Нет каналов, через которые событие затрагивает компанию',
    hits.length ? hits[0].c.basis : [],
  );

  const pin = p.derived.payments_in;
  const pout = p.derived.payments_out;
  const shareIn = pin ? pin.sectors.filter((s) => n.event.sectors.includes(s.key)).reduce((a, s) => a + s.share, 0) : 0;
  const shareOut = pout ? pout.sectors.filter((s) => n.event.sectors.includes(s.key)).reduce((a, s) => a + s.share, 0) : 0;
  const cp = Math.min(1, (shareIn + shareOut) * 2);
  add(
    'counterparty',
    cp,
    cp > 0
      ? `Контрагенты из затронутых отраслей: ≈${Math.round((shareIn + shareOut) * 100)}% платежей`
      : 'Контрагенты из затронутых отраслей в графе платежей не найдены',
    cp > 0 ? ['G:payments_in.sectors', 'G:payments_out.sectors'] : [],
  );

  const region = p.summary.region;
  const regionHit = !!region && n.event.regions.includes(region);
  add(
    'region',
    regionHit ? 1 : 0,
    region
      ? regionHit
        ? `Событие касается региона регистрации: ${region}`
        : n.event.regions.length
          ? 'Регион события не совпадает с регионом регистрации'
          : 'Событие федеральное, без привязки к региону'
      : 'Регион компании неизвестен — компонент не учитывается',
    regionHit ? ['P:REGION'] : [],
  );
  add('macro', n.importance, `Тип события «${n.event.event_label}»: макрозначимость ${Math.round(n.importance * 100)}%`, []);
  const bankFound = n.bankChunks.length > 0;
  add(
    'bank',
    bankFound ? 1 : 0,
    bankFound ? 'По теме есть аналитика Альфа-Банка' : 'Аналитика банка по теме не найдена',
    bankFound ? n.bankChunks.map((c) => `B:${c}`) : [],
  );

  const score = r2(comps.reduce((a, c) => a + c.contribution, 0));
  const level = score >= 0.45 ? 'high' : score >= 0.3 ? 'medium' : score >= 0.18 ? 'low' : 'none';
  const top = [...comps].filter((c) => c.value > 0 && c.key !== 'macro').sort((a, b) => b.contribution - a.contribution);
  const reasons = top.slice(0, 3).map((c) => c.reason);
  const whyShort = hits.length
    ? `${hits[0].c.label}: ${hits[0].c.notes[0] ?? ''}`
    : top[0]?.reason ?? 'Слабая связь с профилем компании';
  return {
    score,
    level,
    components: comps,
    reasons: reasons.length ? reasons : ['Связь с профилем компании слабая'],
    why_short: whyShort,
    confidence: warnings.length ? 'medium' : hits.length ? 'high' : 'low',
    profile_warnings: warnings,
  };
}

function feedItem(p: CompanyProfile, n: MockNews): FeedItem {
  const relevance = relevanceFor(p, n);
  const docs = Array.from(new Set(n.bankChunks.map((c) => MOCK_CHUNKS[c]?.doc_id).filter(Boolean))).map((d) => ({
    doc_id: d as string,
    title: Object.values(MOCK_CHUNKS).find((c) => c.doc_id === d)?.doc_title ?? String(d),
  }));
  return {
    news_id: n.id,
    title: n.title,
    summary: n.summary,
    url: n.url,
    source_name: n.source_name,
    published_at: n.published_at,
    event: n.event,
    relevance,
    duplicates: MOCK_DUPLICATES[n.id] ?? [],
    bank_coverage: { found: docs.length > 0, docs },
    filtered_reason: !n.business ? 'non_business' : relevance.level === 'none' ? 'low_relevance' : null,
  };
}

function buildFeed(p: CompanyProfile, limit: number, includeFiltered: boolean): Feed {
  const all = NEWS.map((n) => feedItem(p, n));
  const items = all
    .filter((i) => !i.filtered_reason)
    .sort((a, b) => b.relevance.score - a.relevance.score || b.published_at.localeCompare(a.published_at));
  const filtered = all.filter((i) => i.filtered_reason);
  return {
    company_id: p.summary.company_id,
    generated_at: nowIso(),
    items: items.slice(0, limit),
    filtered: includeFiltered ? filtered : [],
    stats: {
      news_considered: all.length,
      shown: Math.min(limit, items.length),
      filtered_non_business: filtered.filter((f) => f.filtered_reason === 'non_business').length,
      filtered_low_relevance: filtered.filter((f) => f.filtered_reason === 'low_relevance').length,
    },
  };
}

/* ---------------- инсайты ---------------- */

const STEPS: Array<Omit<TraceStep, 'started_at' | 'step'>> = [
  { kind: 'plan', name: 'plan', title: 'План анализа', status: 'ok', duration_ms: 640, input: { role: 'cfo' }, output_summary: 'План: профиль → новость → событие → аналитика банка → граф платежей → черновик → проверка', source_ids: [], notes: ['План построен по типу события и роли пользователя'], tokens: { prompt: 820, completion: 140 }, model: 'GLM-5.3-Flash' },
  { kind: 'tool', name: 'get_company_profile', title: 'Профиль компании', status: 'ok', duration_ms: 14, input: {}, output_summary: 'Загружен профиль: ОКВЭД, продукты банка, регион, каналы чувствительности', source_ids: ['P:MAINOKVED_CODE', 'P:CL_PRODUCT_LOA_MARK'], notes: [], tokens: null, model: null },
  { kind: 'tool', name: 'get_news', title: 'Текст новости', status: 'ok', duration_ms: 9, input: {}, output_summary: 'Получен текст и метаданные публикации', source_ids: [], notes: [], tokens: null, model: null },
  { kind: 'tool', name: 'classify_event', title: 'Тип события и затронутые отрасли', status: 'ok', duration_ms: 22, input: {}, output_summary: 'Определён тип события и каналы влияния', source_ids: [], notes: [], tokens: null, model: null },
  { kind: 'tool', name: 'search_bank_analytics', title: 'Поиск позиции Альфа-Банка', status: 'empty', duration_ms: 180, input: { q: 'тема события', k: 5 }, output_summary: 'Первый запрос не дал релевантных фрагментов', source_ids: [], notes: ['Порог релевантности 0.35 не пройден'], tokens: null, model: null },
  { kind: 'repair', name: 'search_bank_analytics', title: 'Повторный поиск с переформулированным запросом', status: 'ok', duration_ms: 210, input: { q: 'переформулированный запрос', k: 5 }, output_summary: 'Найдены фрагменты аналитики банка', source_ids: [], notes: ['bank_search_retry: запрос переформулирован'], tokens: null, model: null },
  { kind: 'tool', name: 'get_payment_graph', title: 'Граф платежей и контрагенты', status: 'ok', duration_ms: 31, input: { depth: 1 }, output_summary: 'Отрасли и регионы контрагентов, концентрация топ-5', source_ids: ['G:payments_out.sectors', 'G:payments_in.sectors'], notes: [], tokens: null, model: null },
  { kind: 'llm', name: 'write_insight', title: 'Черновик инсайта', status: 'ok', duration_ms: 3900, input: { sections: 8 }, output_summary: 'Сформирован черновик со ссылками на источники', source_ids: [], notes: [], tokens: { prompt: 3600, completion: 690 }, model: 'Qwen3.6-35B-A3B' },
  { kind: 'validate', name: 'validate_insight', title: 'Проверка ссылок, чисел и цитат', status: 'ok', duration_ms: 40, input: {}, output_summary: '1 замечание: число без источника в разделе «Риски»', source_ids: [], notes: ['unsupported_number → отправлено на доработку'], tokens: null, model: null },
  { kind: 'repair', name: 'repair_insight', title: 'Доработка по замечаниям проверки', status: 'ok', duration_ms: 1200, input: { issues: 1 }, output_summary: 'Утверждение переписано без неподтверждённого числа', source_ids: [], notes: [], tokens: { prompt: 900, completion: 120 }, model: 'Qwen3.6-35B-A3B' },
  { kind: 'final', name: 'finalize', title: 'Готово', status: 'ok', duration_ms: 5, input: {}, output_summary: 'Инсайт сохранён', source_ids: [], notes: [], tokens: null, model: null },
];
const STEP_MS = 650;

interface MockInsightRec {
  envelope: InsightEnvelope;
  createdAt: number;
  fail: boolean;
  result: Insight;
  chat: ChatMessage[];
  chatSeq: number;
}
const INSIGHTS = new Map<string, MockInsightRec>();
const INSIGHT_KEY = new Map<string, string>();

function st(text: string, kind: Statement['kind'], source_ids: string[], confidence: Statement['confidence'] = 'medium'): Statement {
  return { text, kind, source_ids, confidence };
}

function fmtBn(v: number | null | undefined) {
  if (v == null) return 'н/д';
  return `${(v / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млрд`;
}

function buildInsight(p: CompanyProfile, n: MockNews): Insight {
  const fi = feedItem(p, n);
  const o = p.observed;
  const nid = `N:${n.id}`;
  const sources: SourceMap = {};
  const addSrc = (s: Source) => {
    sources[s.id] = s;
    return s.id;
  };
  addSrc({ type: 'news', id: nid, title: n.title, url: n.url, source_name: n.source_name, published_at: n.published_at });
  (MOCK_DUPLICATES[n.id] ?? []).forEach((d) =>
    addSrc({ type: 'news', id: `N:${d.news_id}`, title: d.title, url: d.url, source_name: d.source_name, published_at: n.published_at }),
  );
  const prof = (field: string) => {
    const f = o[field];
    if (!f) return null;
    return addSrc({ type: 'profile', id: `P:${field}`, title: f.title, value: f.value, origin: f.source });
  };
  const graph = (path: string, title: string, value: unknown) =>
    addSrc({ type: 'graph', id: `G:${path}`, title, value, origin: `Граф платежей (df_Uid_payment_hack.csv), агрегат ${path}` });
  const bank = n.bankChunks.map((cid) => {
    const c = MOCK_CHUNKS[cid];
    addSrc({ type: 'bank', id: `B:${cid}`, doc_id: c.doc_id, doc_title: c.doc_title, page: c.page, url: c.url, published_at: c.published_at, text: c.text });
    return c;
  });

  const topChannel = p.channels.find((c) => n.channels[c.key]);
  const channelSrc = (topChannel?.basis ?? []).map((b) => (b.startsWith('P:') ? prof(b.slice(2)) : b)).filter(Boolean) as string[];
  const okved = prof('MAINOKVED_CODE');
  const rev = prof('REVENUE_COMPANY');
  const region = o.REGION?.value ? prof('REGION') : null;
  const pin = p.derived.payments_in;
  const gIn = pin ? graph('payments_in.sectors', 'Отрасли покупателей (входящие платежи)', pin.sectors.slice(0, 5)) : null;
  const pout = p.derived.payments_out;
  const gTop = pout ? graph('payments_out.top5_share', 'Концентрация поставщиков: доля топ-5 в исходящих платежах', pout.top5_share) : null;

  const isRate = n.event.event_type === 'key_rate';
  const outdated = bank.some((b) => b.published_at < '2025-01-01');
  const mode: Insight['mode'] = isRate ? 'llm' : 'rules';

  const what = [
    st(n.title.replace(/\.$/, '') + '.', 'fact', [nid], 'high'),
    st(n.summary.replace(' [Учебная мок-новость]', ''), 'fact', [nid, ...(MOCK_DUPLICATES[n.id] ?? []).map((d) => `N:${d.news_id}`)], 'high'),
  ];
  const why: Statement[] = [];
  if (topChannel) {
    why.push(st(`Канал «${topChannel.label}»: ${topChannel.notes[0]}.`, 'client_link', channelSrc, 'high'));
  }
  why.push(
    st(
      `Основной вид деятельности — ${o.MAINOKVED_NAME?.value ?? p.summary.subtitle} (ОКВЭД ${o.MAINOKVED_CODE?.value ?? 'н/д'}), годовая выручка ${fmtBn(o.REVENUE_COMPANY?.value as number)} ₽.`,
      'client_link',
      [okved, rev].filter(Boolean) as string[],
      'high',
    ),
  );
  if (gIn && pin && pin.sectors.length) {
    why.push(
      st(
        `Крупнейшая отрасль покупателей в графе платежей — «${pin.sectors[0].label}» (≈${Math.round(pin.sectors[0].share * 100)}% входящих платежей); ${Math.round(pin.unknown_profile_share * 100)}% платежей приходится на контрагентов без профиля.`,
        'client_link',
        [gIn],
        'medium',
      ),
    );
  }
  if (region) why.push(st(`Регион регистрации — ${o.REGION.value}.`, 'client_link', [region], 'high'));

  const bankView: Insight['bank_view'] = bank.length
    ? {
        status: outdated ? 'outdated' : 'found',
        note: outdated ? 'Найден только материал банка старше 12 месяцев — используйте с осторожностью.' : '',
        statements: bank.slice(0, 2).map((c) => ({
          text: c.retelling,
          quote: c.quote,
          source_ids: [`B:${c.chunk_id}`],
          doc_title: c.doc_title,
          page: c.page,
          published_at: c.published_at,
          warning: c.published_at < '2025-01-01' ? `Документ от ${c.published_at}: может не отражать текущую ситуацию.` : '',
        })),
      }
    : { status: 'not_found', statements: [], note: 'В корпусе аналитики Альфа-Банка нет материалов по этой теме.' };

  const bankIds = bank.map((c) => `B:${c.chunk_id}`);
  const debt = !!p.products.CL_PRODUCT_LOA_MARK || !!p.products.CL_PRODUCT_LEA_MARK;
  const ai: Statement[] = isRate
    ? [
        st(
          debt
            ? 'Для компании с кредитом и лизингом сохранение ставки означает, что стоимость обслуживания плавающего долга в ближайшие месяцы не снизится.'
            : 'У компании нет кредитных продуктов в банке, поэтому прямой эффект через стоимость долга ограничен; влияние идёт через спрос и стоимость ликвидности.',
          'ai_conclusion',
          [...channelSrc.slice(0, 2), nid],
          'medium',
        ),
        st('Рефинансирование и новые заимствования разумно планировать исходя из сохранения высокой ставки как минимум до конца года.', 'ai_conclusion', [nid, ...bankIds.slice(0, 1)], 'medium'),
      ]
    : [
        st(
          topChannel
            ? `Событие затрагивает компанию прежде всего через канал «${topChannel.label}»; масштаб эффекта по данным профиля оценить нельзя.`
            : 'Прямых каналов влияния на компанию по данным профиля не найдено; событие стоит отслеживать как фон.',
          'ai_conclusion',
          [nid, ...channelSrc.slice(0, 1)],
          'low',
        ),
      ];

  const risks: Statement[] = [
    st(
      isRate
        ? 'Высокая стоимость долга сохраняет давление на процентные расходы и ковенанты по долговой нагрузке.'
        : `Риск: изменение условий по каналу «${topChannel?.label ?? n.event.event_label}» может отразиться на марже.`,
      'ai_conclusion',
      [nid, ...channelSrc.slice(0, 1)],
      'medium',
    ),
  ];
  if (bank[0]) risks.push(st(bank[0].retelling, 'bank_view', [`B:${bank[0].chunk_id}`], 'medium'));
  if (gTop && pout) {
    risks.push(
      st(
        `Концентрация поставщиков: на топ-5 контрагентов приходится ≈${Math.round(pout.top5_share * 100)}% исходящих платежей — изменения у них быстро отразятся на компании.`,
        'ai_conclusion',
        [gTop],
        'medium',
      ),
    );
  }
  const opps: Statement[] = isRate
    ? [st('Свободную ликвидность можно размещать под повышенную доходность, пока ставки высокие.', 'ai_conclusion', [nid], 'medium')]
    : [st('Изменение рыночной ситуации — повод пересмотреть условия с ключевыми контрагентами.', 'ai_conclusion', [nid], 'low')];

  const actions: Statement[] = [
    st(isRate ? 'Пересчитать график процентных платежей по плавающим кредитам на сценарий ставки 14% до конца года.' : 'Оценить чувствительность бюджета к событию в базовом и стрессовом сценарии.', 'action', [nid, ...channelSrc.slice(0, 1)], 'medium'),
    st('Какая доля нашего долга с плавающей ставкой и когда ближайшие погашения?', 'question', channelSrc.slice(0, 1), 'medium'),
    st('Сценарий на 3–6 месяцев: стоимость долга без изменений, спрос покупателей замедляется.', 'scenario', [nid, ...(gIn ? [gIn] : [])], 'low'),
  ];

  const limitations = [
    ...p.data_notes,
    'Параметры кредитного портфеля компании (сумма, ставка, сроки) в данных отсутствуют — эффект оценивается качественно.',
    ...fi.relevance.profile_warnings,
  ];

  return {
    mode,
    models: mode === 'llm' ? { planner: 'GLM-5.3-Flash', writer: 'Qwen3.6-35B-A3B' } : { planner: null, writer: null },
    prompt_version: 'insight-v1',
    headline: isRate
      ? debt
        ? 'Ставка 14% сохраняет дорогой долг для компании с кредитом и лизингом'
        : 'Ставка 14%: прямой эффект через долг ограничен, важнее спрос и ликвидность'
      : `${n.event.event_label}: ${fi.relevance.why_short}`,
    relevance: fi.relevance,
    event: n.event,
    what_happened: what,
    why_it_matters: why,
    risks,
    opportunities: opps,
    bank_view: bankView,
    ai_conclusions: ai,
    actions,
    bank_offer: debt && isRate
      ? { text: 'Обсудить с персональным менеджером фиксацию ставки или хеджирование процентного риска.', product: 'Процентный своп / кредит с фиксированной ставкой', source_ids: channelSrc.slice(0, 1) }
      : null,
    related_news: (MOCK_DUPLICATES[n.id] ?? []).map((d) => ({ ...d, published_at: n.published_at })),
    limitations,
    confidence: fi.relevance.confidence,
    validation: isRate
      ? { passed: true, issues: [{ code: 'unsupported_number', severity: 'warning', message: 'Число без источника было удалено при доработке', path: 'risks[0]' }], repairs: 1 }
      : { passed: true, issues: [], repairs: 0 },
    sources,
  };
}

function progressFor(rec: MockInsightRec): ProgressStep[] {
  const elapsed = Date.now() - rec.createdAt;
  const done = Math.min(STEPS.length, Math.floor(elapsed / STEP_MS));
  const steps: ProgressStep[] = STEPS.slice(0, done).map((s, i) => ({ step: i + 1, kind: s.kind, name: s.name, status: s.status, title: s.title }));
  if (done < STEPS.length) {
    const s = STEPS[done];
    steps.push({ step: done + 1, kind: s.kind, name: s.name, status: 'running', title: s.title });
  }
  return steps;
}

function refresh(rec: MockInsightRec) {
  const e = rec.envelope;
  const elapsed = Date.now() - rec.createdAt;
  if (e.status === 'completed' || e.status === 'failed') return;
  if (rec.fail && elapsed > STEP_MS * 3) {
    e.status = 'failed';
    e.error = 'Недостаточно текста новости для анализа: добавьте текст или ссылку на полную публикацию.';
    e.progress = progressFor(rec).slice(0, 3).map((s, i) => (i === 2 ? { ...s, status: 'error' } : s));
    e.updated_at = nowIso();
    return;
  }
  e.progress = progressFor(rec);
  if (elapsed >= STEP_MS * STEPS.length) {
    e.status = 'completed';
    e.result = rec.result;
  } else {
    e.status = elapsed < 400 ? 'queued' : 'processing';
  }
  e.updated_at = nowIso();
}

function traceFor(rec: MockInsightRec): Trace {
  const t0 = rec.createdAt;
  const steps = rec.envelope.status === 'completed' ? STEPS : STEPS.slice(0, rec.envelope.progress.filter((p) => p.status !== 'running').length);
  const n = NEWS.find((x) => x.id === rec.envelope.news_id);
  const ts: TraceStep[] = steps.map((s, i) => {
    const step: TraceStep = { ...s, step: i + 1, started_at: new Date(t0 + i * STEP_MS).toISOString() };
    if (s.name === 'get_company_profile') step.input = { company_id: rec.envelope.company_id };
    if (s.name === 'get_news') step.input = { news_id: rec.envelope.news_id };
    if (s.name === 'classify_event' && n) step.output_summary = `Тип: ${n.event.event_label}; отрасли: ${n.event.sector_labels.join(', ') || '—'}`;
    if (s.name === 'search_bank_analytics' && s.kind === 'repair') step.source_ids = n ? n.bankChunks.map((c) => `B:${c}`) : [];
    if (s.name === 'get_news') step.source_ids = [`N:${rec.envelope.news_id}`];
    if (rec.result.mode === 'rules' && (s.kind === 'llm' || s.kind === 'plan')) {
      return { ...step, status: 'skipped', model: null, tokens: null, notes: ['LLM недоступна — шаг выполнен правилами'] };
    }
    return step;
  });
  const llm = ts.filter((s) => s.tokens && s.status === 'ok');
  return {
    trace_id: rec.envelope.trace_id,
    insight_id: rec.envelope.insight_id,
    kind: 'insight',
    steps: ts,
    summary: {
      mode: rec.result.mode,
      tool_calls: ts.filter((s) => s.kind === 'tool' || s.kind === 'repair').length,
      llm_calls: llm.length,
      tokens: {
        prompt: llm.reduce((a, s) => a + (s.tokens?.prompt ?? 0), 0),
        completion: llm.reduce((a, s) => a + (s.tokens?.completion ?? 0), 0),
      },
      duration_ms: ts.reduce((a, s) => a + s.duration_ms, 0),
      plan: STEPS.filter((s) => s.kind === 'tool').map((s) => s.name),
      adaptations: ['bank_search_retry: запрос переформулирован', 'repair: удалено число без источника (risks[0])'],
    },
  };
}

function chatAnswer(rec: MockInsightRec, question: string): Omit<ChatMessage, 'id' | 'created_at'> {
  const res = rec.result;
  const q = question.toLowerCase();
  let statements: Statement[];
  let content: string;
  if (q.includes('кредит')) {
    statements = [...res.ai_conclusions.slice(0, 1), ...res.risks.slice(0, 1)];
    content = 'Влияние на обслуживание кредитов по данным профиля и новости:';
  } else if (q.includes('поставщик') || q.includes('покупател')) {
    statements = [...res.why_it_matters.filter((s) => s.source_ids.some((x) => x.startsWith('G:'))), ...res.risks.filter((s) => s.source_ids.some((x) => x.startsWith('G:')))];
    content = 'По графу платежей (1 шаг связей) картина такая:';
  } else if (q.includes('3') && q.includes('6')) {
    statements = [...res.risks, ...res.actions.filter((a) => a.kind === 'scenario')];
    content = 'Риски на горизонте 3–6 месяцев:';
  } else if (q.includes('основан') || q.includes('источник')) {
    statements = [...res.what_happened.slice(0, 1), ...res.why_it_matters.slice(0, 2), ...res.bank_view.statements.slice(0, 1).map((b) => st(b.text, 'bank_view', b.source_ids, 'medium'))];
    content = 'Вывод опирается на три группы источников: текст новости, профиль компании и аналитику банка:';
  } else {
    statements = res.ai_conclusions.slice(0, 2);
    content = 'Точного ответа в данных нет; ближайшее по смыслу из инсайта:';
  }
  if (!statements.length) {
    statements = res.ai_conclusions.slice(0, 1);
  }
  return { role: 'assistant', content, statements, sources: res.sources, trace_id: rec.envelope.trace_id, mode: res.mode };
}

/* ---------------- роутер ---------------- */

function err(status: number, error: string): MockResponse {
  return { status, data: { error } };
}

export async function mockRequest(
  method: string,
  path: string,
  query: URLSearchParams,
  body: unknown,
  headers: Record<string, string>,
): Promise<MockResponse> {
  await new Promise((r) => setTimeout(r, 180 + Math.random() * 320));
  const clientId = headers['X-Client-Id'];
  const m = (re: RegExp) => path.match(re);
  let mm: RegExpMatchArray | null;

  if (method === 'GET' && path === '/companies') {
    const q = (query.get('query') ?? '').toLowerCase();
    const items = PROFILES.map((p) => p.summary).filter(
      (s) => !q || [s.company_id, s.display_name, s.subtitle, s.region ?? ''].some((x) => x.toLowerCase().includes(q)),
    );
    const res: CompanyList = { items, total: items.length, limit: 50, offset: 0, data_source: 'synthetic' };
    return { status: 200, data: res };
  }
  if (method === 'GET' && (mm = m(/^\/companies\/([^/]+)$/))) {
    const p = profile(mm[1]);
    return p ? { status: 200, data: p } : err(404, 'Компания не найдена');
  }
  if (method === 'GET' && (mm = m(/^\/companies\/([^/]+)\/feed$/))) {
    const p = profile(mm[1]);
    if (!p) return err(404, 'Компания не найдена');
    return { status: 200, data: buildFeed(p, Number(query.get('limit') ?? 20), query.get('include_filtered') === 'true') };
  }
  if (method === 'GET' && path === '/relevance') {
    const n = NEWS.find((x) => x.id === query.get('news_id'));
    if (!n) return err(404, 'Новость не найдена');
    const ids = (query.get('company_ids') ?? '').split(',').filter(Boolean);
    const { event, channels: _c, importance: _i, business: _b, bankChunks: _bc, ...news } = n;
    return {
      status: 200,
      data: {
        news,
        event,
        results: ids
          .map(profile)
          .filter((p): p is CompanyProfile => !!p)
          .map((p) => ({ company_id: p.summary.company_id, display_name: p.summary.display_name, subtitle: p.summary.subtitle, relevance: relevanceFor(p, n) })),
      },
    };
  }
  if (method === 'GET' && (mm = m(/^\/news\/([^/]+)$/))) {
    const n = NEWS.find((x) => x.id === mm![1]);
    if (!n) return err(404, 'Новость не найдена');
    const { event: _e, channels: _c, importance: _i, business: _b, bankChunks: _bc, ...news } = n;
    return { status: 200, data: news };
  }
  if (method === 'POST' && path === '/news') {
    const b = (body ?? {}) as { title?: string; text?: string; url?: string };
    if (!b.text && !b.url) return err(400, 'Нужно указать text или url');
    const existing = b.url ? NEWS.find((x) => x.url === b.url) : undefined;
    if (existing) {
      const { event: _e, channels: _c, importance: _i, business: _b, bankChunks: _bc, ...news } = existing;
      return { status: 200, data: news };
    }
    const text = `${b.title ?? ''} ${b.text ?? ''}`.toLowerCase();
    const guess = MOCK_NEWS.find((x) => x.business && x.event.event_label && text.includes(x.event.event_label.split(' ')[0].toLowerCase().slice(0, 6)));
    const kr = /ставк|цб|банк росси/.test(text);
    const base = kr ? MOCK_NEWS[0] : guess ?? MOCK_NEWS[3];
    const n: MockNews = {
      ...base,
      id: uuid(),
      title: b.title || (b.url ? `Публикация ${new URL(b.url).hostname}` : (b.text ?? '').slice(0, 80)),
      summary: (b.text ?? '').slice(0, 400) || 'Текст будет извлечён со страницы по ссылке (в моке не загружается).',
      content: b.text ?? '',
      url: b.url ?? '',
      source_name: b.url ? new URL(b.url).hostname : 'Добавлено пользователем',
      published_at: nowIso(),
      fetched_at: nowIso(),
      origin: 'user',
    };
    NEWS.push(n);
    const { event: _e, channels: _c, importance: _i, business: _b, bankChunks: _bc, ...news } = n;
    return { status: 201, data: news };
  }
  if (method === 'POST' && path === '/insights') {
    const b = body as { company_id: string; news_id: string; role: string; force?: boolean };
    if (clientId && clientId !== b.company_id) return err(403, 'Инсайт недоступен в контексте другой компании');
    const p = profile(b.company_id);
    const n = NEWS.find((x) => x.id === b.news_id);
    if (!p) return err(404, 'Компания не найдена');
    if (!n) return err(404, 'Новость не найдена');
    const key = `${b.company_id}|${b.news_id}|${b.role}`;
    const prev = INSIGHT_KEY.get(key);
    if (prev && !b.force) {
      const rec = INSIGHTS.get(prev)!;
      refresh(rec);
      const res: CreateInsightResponse = { insight_id: prev, status: rec.envelope.status === 'failed' ? 'processing' : (rec.envelope.status as CreateInsightResponse['status']), trace_id: rec.envelope.trace_id, cached: rec.envelope.status === 'completed' };
      return { status: 202, data: res };
    }
    const id = uuid();
    const rec: MockInsightRec = {
      envelope: {
        insight_id: id,
        company_id: b.company_id,
        news_id: b.news_id,
        role: 'cfo',
        status: 'queued',
        error: null,
        trace_id: uuid(),
        created_at: nowIso(),
        updated_at: nowIso(),
        progress: [],
        result: null,
      },
      createdAt: Date.now(),
      fail: n.origin === 'user' && `${n.title} ${n.content}`.trim().length < 40,
      result: buildInsight(p, n),
      chat: [],
      chatSeq: 0,
    };
    INSIGHTS.set(id, rec);
    INSIGHT_KEY.set(key, id);
    return { status: 202, data: { insight_id: id, status: 'queued', trace_id: rec.envelope.trace_id, cached: false } };
  }
  if ((mm = m(/^\/insights\/([^/]+)(\/trace|\/chat|\/feedback)?$/))) {
    const rec = INSIGHTS.get(mm[1]);
    if (!rec) return err(404, 'Инсайт не найден');
    if (clientId && clientId !== rec.envelope.company_id) return err(403, 'Инсайт недоступен в контексте другой компании');
    refresh(rec);
    const sub = mm[2];
    if (!sub && method === 'GET') return { status: 200, data: rec.envelope };
    if (sub === '/trace' && method === 'GET') return { status: 200, data: traceFor(rec) };
    if (sub === '/chat' && method === 'GET') return { status: 200, data: { messages: rec.chat } };
    if (sub === '/chat' && method === 'POST') {
      if (rec.envelope.status !== 'completed') return err(409, 'Инсайт ещё не готов');
      const question = String((body as { question?: string })?.question ?? '').trim();
      if (!question) return err(400, 'Пустой вопрос');
      await new Promise((r) => setTimeout(r, 900));
      rec.chat.push({ id: ++rec.chatSeq, role: 'user', content: question, created_at: nowIso() });
      const msg: ChatMessage = { id: ++rec.chatSeq, created_at: nowIso(), ...chatAnswer(rec, question) };
      rec.chat.push(msg);
      return { status: 200, data: { message: msg, history: rec.chat } };
    }
    if (sub === '/feedback' && method === 'POST') return { status: 200, data: { ok: true } };
  }
  if (method === 'GET' && path === '/system/status') {
    return {
      status: 200,
      data: {
        data_source: 'synthetic',
        profiles: PROFILES.length,
        profiles_version: 'mock-profiles',
        corpus_version: '5295a3704b89',
        news_in_db: NEWS.length,
        llm: { llm_enabled: true, planner: 'GLM-5.3-Flash', writer: 'Qwen3.6-35B-A3B', last_error: null },
        mode: 'llm',
        mock: true,
      },
    };
  }
  if (method === 'GET' && path === '/metrics/summary') {
    return {
      status: 200,
      data: {
        insights_total: 42 + INSIGHTS.size,
        insights_24h: 17 + INSIGHTS.size,
        validation_pass_rate: 0.93,
        bank_view_found_rate: 0.64,
        avg_latency_ms: 8400,
        p95_latency_ms: 15100,
        tokens_24h: { prompt: 61200, completion: 11800 },
        mode_share: { llm: 0.88, rules: 0.12 },
        feedback: { positive: 9, negative: 2 },
        chat_messages_24h: 23,
        feed_requests_24h: 140,
        note: 'Моковые значения для отладки интерфейса',
      },
    };
  }
  return err(404, `Мок не реализован: ${method} ${path}`);
}
