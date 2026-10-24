import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CheckNewsModal } from '../components/CheckNewsModal';
import { FeedCard } from '../components/FeedCard';
import { IconPlus, IconRefresh } from '../components/Icons';
import { EmptyState, ErrorState, Notice, SkeletonCard } from '../components/ui';
import { useClient, useFeed } from '../lib/context';
import { cls, fmtDateTime } from '../lib/format';
import type { Level } from '../api/types';

type LevelFilter = 'all' | Level;

export function NewsPage() {
  const { client } = useClient();
  const { feed, loading, error, reload } = useFeed();
  const [params, setParams] = useSearchParams();
  const [showFiltered, setShowFiltered] = useState(false);
  const [lvl, setLvl] = useState<LevelFilter>('all');
  const checkOpen = params.get('check') === '1';

  const setCheck = (v: boolean) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (v) p.set('check', '1');
        else p.delete('check');
        return p;
      },
      { replace: true },
    );

  const items = useMemo(() => (feed ? feed.items.filter((i) => lvl === 'all' || i.relevance.level === lvl) : []), [feed, lvl]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { high: 0, medium: 0, low: 0 };
    feed?.items.forEach((i) => (c[i.relevance.level] = (c[i.relevance.level] ?? 0) + 1));
    return c;
  }, [feed]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Новости для бизнеса</h1>
          <p className="muted">
            Лента под профиль {client ? <strong>{client.display_name}</strong> : 'клиента'}: значимость считается из отрасли, продуктов, графа
            платежей и региона компании.
          </p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--secondary btn--sm" onClick={reload} disabled={loading} title="Обновить ленту">
            <IconRefresh size={14} /> Обновить
          </button>
          <button className="btn btn--primary" onClick={() => setCheck(true)}>
            <IconPlus size={16} /> Проверить свою новость
          </button>
        </div>
      </div>

      {client?.completeness === 'incomplete' && (
        <Notice tone="warn">
          Неполный профиль клиента: нет полей {client.key_missing.join(', ') || '—'}. Компоненты значимости, зависящие от них, не
          учитываются, уверенность оценок снижена.
        </Notice>
      )}

      <div className="toolbar">
        <div className="seg seg--sm">
          {(
            [
              ['all', `Все${feed ? ` · ${feed.items.length}` : ''}`],
              ['high', `Высокая · ${counts.high}`],
              ['medium', `Средняя · ${counts.medium}`],
              ['low', `Низкая · ${counts.low}`],
            ] as Array<[LevelFilter, string]>
          ).map(([k, l]) => (
            <button key={k} className={cls('seg__btn', lvl === k && 'is-active')} onClick={() => setLvl(k)}>
              {l}
            </button>
          ))}
        </div>
        <label className="toggle">
          <input type="checkbox" checked={showFiltered} onChange={(e) => setShowFiltered(e.target.checked)} />
          <span className="toggle__ui" />
          Показать отфильтрованные{feed ? ` (${feed.filtered.length})` : ''}
        </label>
        {feed && (
          <span className="muted small toolbar__stats">
            Рассмотрено {feed.stats.news_considered} · не о бизнесе {feed.stats.filtered_non_business} · низкая значимость{' '}
            {feed.stats.filtered_low_relevance} · обновлено {fmtDateTime(feed.generated_at)}
          </span>
        )}
      </div>

      {error && <ErrorState title="Лента недоступна" message={error} onRetry={reload} />}

      {!error && (loading || !feed) && (
        <div className="feed">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard lines={2} />
        </div>
      )}

      {feed && !loading && (
        <div className="feed">
          {items.length === 0 && (
            <EmptyState
              title={feed.items.length ? 'Нет событий с выбранной значимостью' : 'Значимых событий для компании нет'}
              text="Попробуйте другой фильтр или проверьте свою новость."
            />
          )}
          {items.map((it) => (
            <FeedCard key={it.news_id} item={it} />
          ))}
          {showFiltered && (
            <>
              <div className="section-title section-title--sub">
                <h2>Отфильтровано</h2>
                <span className="muted small">Не показываются в ленте — с причиной</span>
              </div>
              {feed.filtered.length === 0 && <EmptyState title="Отфильтрованных публикаций нет" />}
              {feed.filtered.map((it) => (
                <FeedCard key={it.news_id} item={it} filtered />
              ))}
            </>
          )}
        </div>
      )}

      {checkOpen && <CheckNewsModal onClose={() => setCheck(false)} />}
    </div>
  );
}
