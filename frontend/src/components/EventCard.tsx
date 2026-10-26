import type { FeedItem } from '../api/types';
import { cls, fmtDateTime, fmtRelative, LEVEL_SHORT } from '../lib/format';
import { eventIcon } from './eventIcon';
import { IconChevronRight } from './Icons';

const FILTER_REASON: Record<string, string> = {
  non_business: 'Не о бизнесе',
  low_relevance: 'Низкая значимость',
};

/** Карточка события в списке: вся поверхность — одна кнопка выбора, вложенных ссылок нет. */
export function EventCard({ item, selected, filtered, onSelect }: { item: FeedItem; selected: boolean; filtered?: boolean; onSelect: () => void }) {
  const r = item.relevance;
  return (
    <button
      type="button"
      className={cls('event-card', selected && 'is-selected', filtered && 'event-card--filtered')}
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
    >
      <span className="event-card__thumb" aria-hidden="true">
        {eventIcon(item.event.event_type)}
      </span>
      <span className="event-card__body">
        <span className="event-card__meta">
          {filtered ? (
            <span className="tag tag--none">{FILTER_REASON[item.filtered_reason ?? ''] ?? 'Отфильтровано'}</span>
          ) : (
            <span className={cls('tag', `tag--${r.level}`)}>{LEVEL_SHORT[r.level]}</span>
          )}
          <span className="event-card__date" title={fmtDateTime(item.published_at)}>
            {fmtRelative(item.published_at)}
          </span>
        </span>
        <span className="event-card__title">{item.title}</span>
        {!filtered && r.why_short && (
          <span className="event-card__why">
            <strong>Почему для вас:</strong> {r.why_short}
          </span>
        )}
        {filtered && item.summary && <span className="event-card__why">{item.summary}</span>}
      </span>
      <span className="event-card__chev" aria-hidden="true">
        <IconChevronRight size={18} />
      </span>
    </button>
  );
}
