import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { FeedItem } from '../api/types';
import { useClient } from '../lib/context';
import { cls, DIRECTION_LABEL, fmtDateTime, fmtPct } from '../lib/format';
import { IconAlert, IconArrowRight, IconBank, IconChevron, IconCompare, IconExternal } from './Icons';
import { Chip, LevelBadge, ScoreBar } from './ui';

const FILTER_REASON: Record<string, string> = {
  non_business: 'Не относится к бизнесу',
  low_relevance: 'Низкая значимость для компании',
};

export function FeedCard({ item, filtered }: { item: FeedItem; filtered?: boolean }) {
  const { href } = useClient();
  const [open, setOpen] = useState(false);
  const [dupOpen, setDupOpen] = useState(false);
  const r = item.relevance;
  const maxContribution = Math.max(0.0001, ...r.components.map((c) => c.weight));

  return (
    <article className={cls('card', 'feed-card', `feed-card--${r.level}`, filtered && 'feed-card--filtered')}>
      <div className="feed-card__meta">
        {filtered ? (
          <Chip tone="neutral">{FILTER_REASON[item.filtered_reason ?? ''] ?? 'Отфильтровано'}</Chip>
        ) : (
          <LevelBadge level={r.level} />
        )}
        <Chip tone="dark">{item.event.event_label}</Chip>
        {item.event.direction && DIRECTION_LABEL[item.event.direction] && <Chip>{DIRECTION_LABEL[item.event.direction]}</Chip>}
        {item.bank_coverage.found && (
          <Chip
            tone="red"
            icon={<IconBank size={12} />}
            title={item.bank_coverage.docs.map((d) => d.title).join('\n')}
          >
            позиция банка есть
          </Chip>
        )}
        <span className="feed-card__source">
          {item.source_name} · {fmtDateTime(item.published_at)}
        </span>
      </div>

      <h3 className="feed-card__title">
        <Link to={href(`/news/${item.news_id}`)}>{item.title}</Link>
      </h3>
      {item.summary && <p className="feed-card__summary">{item.summary}</p>}

      {!filtered && (
        <div className="feed-card__why">
          <span className="why-label">Почему для вас</span>
          <span>{r.why_short}</span>
        </div>
      )}

      {r.profile_warnings.length > 0 && (
        <div className="feed-card__warn">
          <IconAlert size={14} />
          {r.profile_warnings.join('; ')}
        </div>
      )}

      <div className="feed-card__bottom">
        <ScoreBar score={r.score} level={r.level} />
        <span className="muted small">уверенность: {r.confidence === 'high' ? 'высокая' : r.confidence === 'medium' ? 'средняя' : 'низкая'}</span>
        {item.duplicates.length > 0 && (
          <button className="link-btn" onClick={() => setDupOpen((v) => !v)}>
            ещё {item.duplicates.length} {item.duplicates.length === 1 ? 'источник' : item.duplicates.length < 5 ? 'источника' : 'источников'}
          </button>
        )}
        {r.components.length > 0 && (
          <button className={cls('link-btn', open && 'is-open')} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            Из чего складывается оценка <IconChevron size={14} />
          </button>
        )}
        <div className="feed-card__actions">
          {item.url && (
            <a className="btn btn--ghost btn--sm" href={item.url} target="_blank" rel="noreferrer">
              Первоисточник <IconExternal size={14} />
            </a>
          )}
          <Link className="btn btn--ghost btn--sm" to={href(`/compare?news_id=${item.news_id}`)} title="Сравнить значимость для других клиентов">
            <IconCompare size={14} />
          </Link>
          <Link className="btn btn--primary btn--sm" to={href(`/news/${item.news_id}`)}>
            Разобрать для компании <IconArrowRight size={14} />
          </Link>
        </div>
      </div>

      {dupOpen && (
        <ul className="dups">
          {item.duplicates.map((d) => (
            <li key={d.news_id}>
              <span className="strong">{d.source_name}</span> — {d.title}{' '}
              {d.url && (
                <a href={d.url} target="_blank" rel="noreferrer" className="ext">
                  <IconExternal size={12} />
                </a>
              )}
            </li>
          ))}
        </ul>
      )}

      {open && (
        <div className="components">
          <table className="comp-table">
            <thead>
              <tr>
                <th>Компонент</th>
                <th className="num">Вклад</th>
                <th>Обоснование</th>
              </tr>
            </thead>
            <tbody>
              {r.components.map((c) => (
                <tr key={c.key} className={c.contribution <= 0 ? 'is-zero' : ''}>
                  <td>
                    <div className="strong">{c.label}</div>
                    <div className="muted small">
                      значение {fmtPct(c.value)} × вес {fmtPct(c.weight)}
                    </div>
                  </td>
                  <td className="num">
                    <div className="contrib">
                      <div className="contrib__bar">
                        <span style={{ width: `${(c.contribution / maxContribution) * 100}%` }} />
                      </div>
                      <span>+{c.contribution.toFixed(2)}</span>
                    </div>
                  </td>
                  <td>
                    {c.reason}
                    {c.evidence.length > 0 && (
                      <div className="evidence">
                        {c.evidence.map((e) => (
                          <code key={e}>{e}</code>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.reasons.length > 0 && (
            <div className="reasons">
              <div className="muted small strong">Причины значимости</div>
              <ul>
                {r.reasons.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
