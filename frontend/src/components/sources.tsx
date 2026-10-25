import { createContext, useContext, type ReactNode } from 'react';
import type { Source, SourceMap } from '../api/types';
import { cls, fmtDate, fmtDateTime, fmtPct, fmtValue, SOURCE_PREFIX_LABEL } from '../lib/format';
import { IconBank, IconClose, IconDoc, IconExternal, IconGraph, IconNews, IconProfile } from './Icons';
import { useEscape } from './ui';

export interface SourceRegistry {
  number: (id: string) => number | undefined;
  get: (id: string) => Source | undefined;
  open: (id: string) => void;
  activeId: string | null;
}

const Ctx = createContext<SourceRegistry | null>(null);
export const SourceProvider = ({ value, children }: { value: SourceRegistry; children: ReactNode }) => (
  <Ctx.Provider value={value}>{children}</Ctx.Provider>
);
export function useSources(): SourceRegistry {
  const v = useContext(Ctx);
  if (!v) throw new Error('SourceProvider missing');
  return v;
}

const prefix = (id: string) => id.split(':')[0];

/** Кликабельные маркеры [1][2] для source_ids утверждения. */
export function Markers({ ids }: { ids: string[] }) {
  const reg = useSources();
  if (!ids?.length) return <span className="marker marker--none" title="У утверждения нет ссылок на источники">без источника</span>;
  return (
    <span className="markers">
      {ids.map((id) => {
        const n = reg.number(id);
        const s = reg.get(id);
        return (
          <button
            key={id}
            type="button"
            className={cls('marker', `marker--${prefix(id)}`, !s && 'marker--missing', reg.activeId === id && 'is-active')}
            onClick={() => reg.open(id)}
            title={s ? `${SOURCE_PREFIX_LABEL[prefix(id)] ?? 'Источник'}: ${sourceTitle(s)}` : `${id} — нет в списке источников ответа`}
          >
            {n ?? '?'}
          </button>
        );
      })}
    </span>
  );
}

/** Чипы признаков клиента (P:/G:), показывают поле и значение. */
export function FeatureChips({ ids }: { ids: string[] }) {
  const reg = useSources();
  const feats = ids.filter((id) => id.startsWith('P:') || id.startsWith('G:'));
  if (!feats.length) return null;
  return (
    <span className="features">
      {feats.map((id) => {
        const s = reg.get(id);
        const isP = id.startsWith('P:');
        let label = id.slice(2);
        if (s && (s.type === 'profile' || s.type === 'graph')) {
          label = `${s.title}: ${shortValue(s.value, id.slice(2))}`;
        }
        return (
          <button key={id} type="button" className={cls('feature', isP ? 'feature--p' : 'feature--g')} onClick={() => reg.open(id)}>
            {isP ? <IconProfile size={12} /> : <IconGraph size={12} />}
            <span>{label}</span>
          </button>
        );
      })}
    </span>
  );
}

function shortValue(v: unknown, field: string): string {
  if (Array.isArray(v)) return `${v.length} знач.`;
  if (typeof v === 'number' && v > 0 && v < 1 && !/_MARK$|_FLAG$/.test(field)) return fmtPct(v);
  const s = fmtValue(v, field);
  return s.length > 40 ? s.slice(0, 38) + '…' : s;
}

export function sourceTitle(s: Source): string {
  switch (s.type) {
    case 'news':
      return s.title;
    case 'bank':
      return `${s.doc_title}${s.page ? `, стр. ${s.page}` : ''}`;
    default:
      return s.title;
  }
}

function ValueView({ value, field }: { value: unknown; field: string }) {
  if (Array.isArray(value) && value.every((x) => x && typeof x === 'object' && 'share' in x)) {
    const arr = value as Array<{ label?: string; key?: string; share: number }>;
    const max = Math.max(0.0001, ...arr.map((x) => x.share));
    return (
      <div className="bars">
        {arr.map((x, i) => (
          <div className="bar" key={i}>
            <span className="bar__label">{x.label ?? x.key}</span>
            <span className="bar__track">
              <span style={{ width: `${(x.share / max) * 100}%` }} />
            </span>
            <span className="bar__val">{fmtPct(x.share, 1)}</span>
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === 'number' && value > 0 && value < 1 && !/_MARK$|_FLAG$/.test(field)) {
    return (
      <div className="value-big">
        {fmtPct(value, 1)} <span className="muted small">({value})</span>
      </div>
    );
  }
  if (value !== null && typeof value === 'object') {
    return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
  }
  return <div className="value-big">{fmtValue(value, field)}</div>;
}

export function SourcePanel({ id, source, number, onClose }: { id: string; source?: Source; number?: number; onClose: () => void }) {
  useEscape(onClose);
  const p = prefix(id);
  const icon =
    p === 'N' ? <IconNews size={18} /> : p === 'B' ? <IconBank size={18} /> : p === 'P' ? <IconProfile size={18} /> : <IconGraph size={18} />;
  return (
    <aside className="drawer" role="dialog" aria-label="Источник">
      <div className="drawer__head">
        <span className={cls('drawer__type', `drawer__type--${p}`)}>
          {icon}
          {SOURCE_PREFIX_LABEL[p] ?? 'Источник'}
        </span>
        {number && <span className="marker marker--static">{number}</span>}
        <span className="drawer__spacer" />
        <button className="icon-btn" onClick={onClose} aria-label="Закрыть">
          <IconClose />
        </button>
      </div>
      <div className="drawer__body">
        {!source && (
          <div className="notice notice--warn">
            <div>
              Источник <code>{id}</code> упомянут в ответе, но не передан в списке источников — проверить его нельзя. Такое утверждение
              следует считать неподтверждённым.
            </div>
          </div>
        )}
        {source?.type === 'news' && (
          <>
            <h3 className="drawer__title">{source.title}</h3>
            <dl className="kv">
              <dt>Источник</dt>
              <dd>{source.source_name}</dd>
              <dt>Опубликовано</dt>
              <dd>{fmtDateTime(source.published_at)}</dd>
            </dl>
            {source.excerpt && <blockquote className="fragment fragment--news">{source.excerpt}</blockquote>}
            {source.url && (
              <a className="btn btn--secondary btn--sm" href={source.url} target="_blank" rel="noreferrer">
                Открыть первоисточник <IconExternal size={14} />
              </a>
            )}
          </>
        )}
        {source?.type === 'bank' && (
          <>
            <span className="badge-bank">
              <IconBank size={12} /> Аналитика Альфа-Банка
            </span>
            <h3 className="drawer__title">{source.doc_title}</h3>
            <dl className="kv">
              <dt>Страница</dt>
              <dd>{source.page ?? '—'}</dd>
              <dt>Дата документа</dt>
              <dd>{fmtDate(source.published_at)}</dd>
              <dt>Документ</dt>
              <dd>
                <code>{source.doc_id}</code>
              </dd>
            </dl>
            <div className="muted small strong">Фрагмент документа</div>
            <blockquote className="fragment">{source.text}</blockquote>
            {source.url && (
              <a className="btn btn--secondary btn--sm" href={source.url} target="_blank" rel="noreferrer">
                <IconDoc size={14} /> Открыть документ{source.page ? `, стр. ${source.page}` : ''} <IconExternal size={14} />
              </a>
            )}
          </>
        )}
        {(source?.type === 'profile' || source?.type === 'graph') && (
          <>
            <h3 className="drawer__title">{source.title}</h3>
            <dl className="kv">
              <dt>{source.type === 'profile' ? 'Поле' : 'Агрегат'}</dt>
              <dd>
                <code>{id.slice(2)}</code>
              </dd>
              <dt>Происхождение</dt>
              <dd>{source.origin}</dd>
            </dl>
            <div className="muted small strong">Значение</div>
            <ValueView value={source.value} field={id.slice(2)} />
            {source.type === 'profile' && (
              <p className="muted small">Прямое наблюдение из данных банка о клиенте — не вывод модели.</p>
            )}
            {source.type === 'graph' && (
              <p className="muted small">Вычислено по графу платежей/группы. Период и единицы платежей в данных не указаны.</p>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

export function buildOrder(ids: Iterable<string>): Map<string, number> {
  const m = new Map<string, number>();
  for (const id of ids) if (!m.has(id)) m.set(id, m.size + 1);
  return m;
}

export function mergeSources(a: SourceMap, b?: SourceMap): SourceMap {
  return b ? { ...a, ...b } : a;
}
