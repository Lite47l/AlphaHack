import type { Confidence, Level, StatementKind } from '../api/types';

const dtf = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' });
const df = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });

export function fmtDateTime(s?: string | null): string {
  if (!s) return '—';
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : dtf.format(d);
}

export function fmtDate(s?: string | null): string {
  if (!s) return '—';
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : df.format(d);
}

export function fmtRelative(s?: string | null): string {
  if (!s) return '';
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'только что';
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} дн назад`;
  return fmtDate(s);
}

export function fmtBn(v?: number | null, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${(v / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: 0 })} млрд ₽`;
}

export function fmtMoneyShort(v?: number | null): string {
  if (v === null || v === undefined) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} млрд`;
  if (a >= 1e6) return `${(v / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн`;
  return v.toLocaleString('ru-RU');
}

export function fmtPct(v?: number | null, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const min = Math.pow(10, -digits) / 100;
  if (v > 0 && v < min) return `<${(min * 100).toLocaleString('ru-RU')}%`;
  return `${(v * 100).toLocaleString('ru-RU', { maximumFractionDigits: digits })}%`;
}

export function fmtNum(v?: number | null): string {
  if (v === null || v === undefined) return '—';
  return v.toLocaleString('ru-RU');
}

export function fmtMs(ms?: number | null): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${Math.round(ms)} мс`;
  return `${(ms / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} с`;
}

export const LEVEL_LABEL: Record<Level, string> = {
  high: 'Высокая значимость',
  medium: 'Средняя значимость',
  low: 'Низкая значимость',
  none: 'Не значимо',
};
export const LEVEL_SHORT: Record<Level, string> = { high: 'Высокая', medium: 'Средняя', low: 'Низкая', none: 'Нет' };

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: 'высокая',
  medium: 'средняя',
  low: 'низкая',
};

export const DIRECTION_LABEL: Record<string, string> = {
  hold: 'без изменений',
  up: 'рост',
  down: 'снижение',
};

export const KIND_LABEL: Record<StatementKind, string> = {
  fact: 'Факт из новости',
  client_link: 'Связь с компанией',
  ai_conclusion: 'Вывод AI',
  bank_view: 'Позиция банка',
  action: 'Действие',
  question: 'Вопрос',
  scenario: 'Сценарий',
};

export const STEP_KIND_LABEL: Record<string, string> = {
  plan: 'План',
  tool: 'Инструмент',
  check: 'Проверка',
  llm: 'LLM',
  validate: 'Валидация',
  repair: 'Доработка',
  final: 'Итог',
};

export const STEP_STATUS_LABEL: Record<string, string> = {
  ok: 'выполнено',
  empty: 'пусто',
  error: 'ошибка',
  skipped: 'пропущено',
  running: 'выполняется',
};

export const SOURCE_PREFIX_LABEL: Record<string, string> = {
  N: 'Новость',
  B: 'Аналитика Альфа-Банка',
  P: 'Поле профиля',
  G: 'Граф платежей',
};

export function fmtValue(v: unknown, field?: string): string {
  if (v === null || v === undefined || v === '') return 'нет данных';
  if (typeof v === 'number') {
    if (field && /_MARK$|_FLAG$/.test(field) && (v === 0 || v === 1)) return v === 1 ? 'да (1)' : 'нет (0)';
    if (field && /REVENUE/.test(field)) return `${v.toLocaleString('ru-RU')} ₽ (${fmtBn(v)})`;
    return v.toLocaleString('ru-RU');
  }
  if (typeof v === 'boolean') return v ? 'да' : 'нет';
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

export function cls(...xs: Array<string | false | null | undefined>): string {
  return xs.filter(Boolean).join(' ');
}
