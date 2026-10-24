// Типы строго по docs/api_contract.md (v1.0).

export type Level = 'high' | 'medium' | 'low' | 'none';
export type Confidence = 'high' | 'medium' | 'low';
export type Role = 'cfo' | 'ceo' | 'treasurer' | 'accountant';

/* ---------- Новости (Go) ---------- */

export interface News {
  id: string;
  title: string;
  summary: string;
  content: string;
  url: string;
  source_name: string;
  published_at: string;
  fetched_at: string;
  origin: 'collector' | 'snapshot' | 'user';
}

export interface NewsList {
  items: News[];
  limit: number;
  offset: number;
}

export interface CreateNewsRequest {
  title?: string;
  text?: string;
  url?: string;
}

export interface KnowledgeItem {
  id: string;
  title: string;
  institution: string;
  document_url: string;
  published_at: string;
}

/* ---------- Компании (AI) ---------- */

export interface Sector {
  key: string;
  label: string;
}

export interface CompanySummary {
  company_id: string;
  display_name: string;
  subtitle: string;
  okved_code: string | null;
  region: string | null;
  revenue: number | null;
  cl_type: string | null;
  sectors: Sector[];
  profile_status: 'matched' | 'ambiguous';
  completeness: 'complete' | 'incomplete';
  key_missing: string[];
  top_channels: string[];
}

export interface CompanyList {
  items: CompanySummary[];
  total: number;
  limit: number;
  offset: number;
  data_source: 'real' | 'synthetic';
}

export interface ObservedField {
  value: string | number | null;
  title: string;
  source: string;
}

export interface Channel {
  key: string;
  label: string;
  strength: number;
  basis: string[];
  notes: string[];
}

export interface ShareItem {
  key: string;
  label: string;
  share: number;
}

export interface Counterparty {
  company_id: string;
  amt: number;
  cnt: number;
  share: number;
  okved_code: string | null;
  okved_name: string | null;
  region: string | null;
  in_profile: boolean;
}

export interface PaymentsAggregate {
  amount: number;
  count: number;
  counterparties: number;
  top5_share: number;
  max_share: number;
  unknown_profile_share: number;
  sectors: ShareItem[];
  regions: ShareItem[];
  fts_countries: ShareItem[];
  top: Counterparty[];
  missing_amount_rows?: number;
}

export interface CompanyDerived {
  revenue_rank?: { okved_class: string; rank: number; of: number; note: string } | null;
  group?: {
    group_id: string;
    size: number;
    revenue_sum: number;
    member_sectors: Array<{ key: string; label: string; companies?: number }>;
    note: string;
  } | null;
  payments_out?: PaymentsAggregate | null;
  payments_in?: PaymentsAggregate | null;
  persons?: {
    linked_persons: number;
    regions: Array<ShareItem | string>;
    companies_via_shared_persons: Array<Record<string, unknown> | string>;
    note: string;
  } | null;
  [key: string]: unknown;
}

export interface CompanyProfile {
  summary: CompanySummary;
  observed: Record<string, ObservedField>;
  products: Record<string, number | null>;
  missing_fields: string[];
  channels: Channel[];
  derived: CompanyDerived;
  data_notes: string[];
}

/* ---------- Лента ---------- */

export interface Event {
  event_type: string;
  event_label: string;
  sectors: string[];
  sector_labels: string[];
  direction: string | null;
  regions: string[];
}

export interface RelevanceComponent {
  key: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  reason: string;
  evidence: string[];
}

export interface Relevance {
  score: number;
  level: Level;
  components: RelevanceComponent[];
  reasons: string[];
  why_short: string;
  confidence: Confidence;
  profile_warnings: string[];
  freshness?: number;
  channels_hit?: Array<{ key: string; label: string; impact: number }>;
}

export interface Duplicate {
  news_id: string;
  title: string;
  source_name: string;
  url: string;
}

export interface BankCoverage {
  found: boolean;
  docs: Array<{ doc_id: string; title: string }>;
}

export interface FeedItem {
  news_id: string;
  title: string;
  summary: string;
  url: string;
  source_name: string;
  published_at: string;
  event: Event;
  relevance: Relevance;
  duplicates: Duplicate[];
  bank_coverage: BankCoverage;
  filtered_reason: 'non_business' | 'low_relevance' | null;
}

export interface Feed {
  company_id: string;
  generated_at: string;
  items: FeedItem[];
  filtered: FeedItem[];
  stats: {
    news_considered: number;
    shown: number;
    filtered_non_business: number;
    filtered_low_relevance: number;
    /** Не в контракте v1.0, но отдаётся AI-сервисом: число значимых событий по всей ленте */
    significant?: number;
    clusters?: number;
  };
}

export interface RelevanceCompare {
  news: News;
  event: Event;
  results: Array<{
    company_id: string;
    display_name: string;
    subtitle: string;
    relevance: Relevance;
  }>;
}

/* ---------- Инсайты ---------- */

export type InsightStatus = 'queued' | 'processing' | 'completed' | 'failed';

export interface CreateInsightRequest {
  company_id: string;
  news_id: string;
  role: Role;
  force?: boolean;
}

export interface CreateInsightResponse {
  insight_id: string;
  status: 'queued' | 'processing' | 'completed';
  trace_id: string;
  cached: boolean;
}

export type StepKind = 'plan' | 'tool' | 'check' | 'llm' | 'validate' | 'repair' | 'final';
export type StepStatus = 'ok' | 'empty' | 'error' | 'skipped' | 'running' | string;

export interface ProgressStep {
  step: number;
  kind: StepKind | string;
  name: string;
  status: StepStatus;
  title: string;
}

export type StatementKind =
  | 'fact'
  | 'client_link'
  | 'ai_conclusion'
  | 'bank_view'
  | 'action'
  | 'question'
  | 'scenario';

export interface Statement {
  text: string;
  source_ids: string[];
  kind: StatementKind;
  /** в ответах чата может отсутствовать */
  confidence?: Confidence;
}

export interface BankStatement {
  text: string;
  quote: string;
  source_ids: string[];
  doc_title: string;
  page: number | null;
  published_at: string | null;
  warning: string;
  url?: string;
}

export interface NewsSource {
  type: 'news';
  id: string;
  title: string;
  url: string;
  source_name: string;
  published_at: string;
  excerpt?: string;
}
export interface BankSource {
  type: 'bank';
  id: string;
  doc_id: string;
  doc_title: string;
  page: number | null;
  url: string;
  published_at: string;
  text: string;
}
export interface ProfileSource {
  type: 'profile';
  id: string;
  title: string;
  value: unknown;
  origin: string;
}
export interface GraphSource {
  type: 'graph';
  id: string;
  title: string;
  value: unknown;
  origin: string;
}
export type Source = NewsSource | BankSource | ProfileSource | GraphSource;
export type SourceMap = Record<string, Source>;

export interface ValidationIssue {
  code: string;
  severity: 'blocking' | 'warning';
  message: string;
  path: string;
}

export interface RelatedNews {
  news_id: string;
  title: string;
  source_name: string;
  url: string;
  published_at: string;
}

export interface Insight {
  mode: 'llm' | 'rules';
  models: Record<string, string | null>;
  prompt_version: string;
  headline: string;
  relevance: Relevance;
  event: Event;
  what_happened: Statement[];
  why_it_matters: Statement[];
  risks: Statement[];
  opportunities: Statement[];
  bank_view: {
    status: 'found' | 'not_found' | 'outdated';
    statements: BankStatement[];
    note: string;
  };
  ai_conclusions: Statement[];
  actions: Statement[];
  bank_offer: { text: string; product: string; source_ids: string[] } | null;
  related_news: RelatedNews[];
  limitations: string[];
  confidence: Confidence;
  validation: { passed: boolean; issues: ValidationIssue[]; repairs: number };
  sources: SourceMap;
}

export interface InsightEnvelope {
  insight_id: string;
  company_id: string;
  news_id: string;
  role: Role;
  status: InsightStatus;
  error: string | null;
  trace_id: string;
  created_at: string;
  updated_at: string;
  progress: ProgressStep[];
  result: Insight | null;
}

export interface TraceStep {
  step: number;
  kind: StepKind | string;
  name: string;
  title: string;
  status: StepStatus;
  started_at: string;
  duration_ms: number;
  input: unknown;
  output_summary: string;
  source_ids: string[];
  notes: string[];
  tokens: { prompt: number; completion: number } | null;
  model: string | null;
}

export interface Trace {
  trace_id: string;
  insight_id: string;
  kind: 'insight' | 'chat';
  steps: TraceStep[];
  summary: {
    mode: 'llm' | 'rules';
    tool_calls: number;
    llm_calls: number;
    tokens: { prompt: number; completion: number };
    duration_ms: number;
    plan: string[];
    adaptations: string[];
  };
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  statements?: Statement[];
  sources?: SourceMap;
  trace_id?: string;
  mode?: 'llm' | 'rules';
  created_at: string;
}

export interface ChatResponse {
  message: ChatMessage;
  history: ChatMessage[];
}

export interface ChatHistory {
  messages: ChatMessage[];
}

/* ---------- Справочное ---------- */

export interface SystemStatus {
  data_source: 'real' | 'synthetic';
  profiles: number;
  profiles_version: string;
  corpus_version: string;
  news_in_db: number;
  llm: { llm_enabled: boolean; [key: string]: unknown };
  mode: 'llm' | 'rules';
  [key: string]: unknown;
}

// Структура метрик расширяемая — показываем любые поля.
export type MetricsSummary = Record<string, unknown>;

export interface ApiErrorBody {
  error: string;
}
