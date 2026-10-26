import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { FeedItem } from '../api/types';
import { EventCard } from '../components/EventCard';
import { EventDetail } from '../components/EventDetail';
import { IconBank, IconFlag, IconNews, IconRefresh, IconChevronRight } from '../components/Icons';
import { EmptyState, ErrorState, Notice, SkeletonCard } from '../components/ui';
import { FEED_LIMIT, useClient, useFeed } from '../lib/context';
import { cls, fmtDateTime, plural } from '../lib/format';
import { useMediaQuery } from '../lib/hooks';

type Filter = 'all' | 'important' | 'bank';
type Sort = 'relevance' | 'date';

const FILTER_NOTE: Record<Exclude<Filter, 'all'>, string> = {
  important: 'Показаны события высокой и средней значимости',
  bank: 'Показаны события, по которым найдена аналитика Альфа-Банка',
};

export function NewsPage() {
  const { client, clientId } = useClient();
  const { feed: rawFeed, loading, error, reload, significant } = useFeed();
  // после смены клиента на один кадр может остаться лента прежнего — её не показываем
  const feed = rawFeed && rawFeed.company_id === clientId ? rawFeed : null;
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<Filter>('all');
  const [sort, setSort] = useState<Sort>('relevance');
  const [showFiltered, setShowFiltered] = useState(false);
  const wide = useMediaQuery('(min-width: 1101px)');

  const selectedParam = params.get('event');
  const setSelected = (id: string | null) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (id) p.set('event', id);
      else p.delete('event');
      return p;
    });
    if (id && !wide) window.scrollTo({ top: 0 });
  };

  // при смене клиента ленту грузим заново; параметр события удаляет сам выбор клиента
  useEffect(() => {
    if (feed && selectedParam && ![...feed.items, ...feed.filtered].some((i) => i.news_id === selectedParam)) {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.delete('event');
          return p;
        },
        { replace: true },
      );
    }
  }, [feed, selectedParam, setParams]);

  const items = useMemo<FeedItem[]>(() => {
    if (!feed) return [];
    let xs = feed.items;
    if (filter === 'important') xs = xs.filter((i) => i.relevance.level === 'high' || i.relevance.level === 'medium');
    if (filter === 'bank') xs = xs.filter((i) => i.bank_coverage.found);
    if (sort === 'date') xs = [...xs].sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at));
    return xs;
  }, [feed, filter, sort]);

  const everything = useMemo(() => (feed ? [...feed.items, ...feed.filtered] : []), [feed]);
  const picked = selectedParam ? everything.find((i) => i.news_id === selectedParam) : undefined;
  const selected: FeedItem | undefined = picked ?? (wide ? items[0] : undefined);
  const selectedIsFiltered = !!selected && !!feed && feed.filtered.some((i) => i.news_id === selected.news_id);

  const bankCount = feed ? feed.items.filter((i) => i.bank_coverage.found).length : 0;
  const capped = !!feed && feed.items.length >= FEED_LIMIT;
  const toggleFilter = (f: Exclude<Filter, 'all'>) => setFilter((cur) => (cur === f ? 'all' : f));

  const summary = feed ? (
    <div className="summary">
      <button className="stat" onClick={() => setFilter('all')} aria-pressed={filter === 'all'} title="Показать все события">
        <span className="stat__icon">
          <IconNews size={22} />
        </span>
        <span className="stat__body">
          <span className="stat__num">
            {feed.items.length}
            {capped ? '+' : ''}
          </span>
          <span className="stat__label">{plural(feed.items.length, 'событие', 'события', 'событий')} в ленте</span>
          {capped && <span className="stat__hint">показаны первые {FEED_LIMIT}</span>}
        </span>
      </button>
      <button className={cls('stat', filter === 'important' && 'is-active')} onClick={() => toggleFilter('important')} aria-pressed={filter === 'important'}>
        <span className="stat__icon stat__icon--red">
          <IconFlag size={22} />
        </span>
        <span className="stat__body">
          <span className="stat__num">{significant}</span>
          <span className="stat__label">{plural(significant, 'важное', 'важных', 'важных')}</span>
          <span className="stat__hint">высокая и средняя значимость</span>
        </span>
        <span className="stat__chev">
          <IconChevronRight size={18} />
        </span>
      </button>
      <button className={cls('stat', filter === 'bank' && 'is-active')} onClick={() => toggleFilter('bank')} aria-pressed={filter === 'bank'}>
        <span className="stat__icon">
          <IconBank size={22} />
        </span>
        <span className="stat__body">
          <span className="stat__num">{bankCount}</span>
          <span className="stat__label">с аналитикой банка</span>
          <span className="stat__hint">{capped ? `среди ${feed.items.length} показанных` : 'есть материал Альфа-Банка'}</span>
        </span>
        <span className="stat__chev">
          <IconChevronRight size={18} />
        </span>
      </button>
    </div>
  ) : null;

  return (
    <div className={cls('page', 'page--events', !wide && !!picked && 'is-detail')}>
      <div className="page-head">
        <div>
          <h1 className="page-title">Что важно для вашей компании</h1>
          <p className="page-sub">Новости и их возможное влияние на ваш бизнес</p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--secondary btn--sm" onClick={reload} disabled={loading} title="Обновить ленту">
            <IconRefresh size={14} /> Обновить
          </button>
        </div>
      </div>

      {client?.completeness === 'incomplete' && (
        <Notice tone="warn">
          Неполный профиль клиента: нет полей {client.key_missing.join(', ') || '—'}. Компоненты значимости, зависящие от них, не
          учитываются, уверенность оценок снижена.
        </Notice>
      )}

      {error && <ErrorState title="Лента недоступна" message={error} onRetry={reload} />}

      {!error && (loading || !feed) && (
        <>
          <div className="summary">
            <SkeletonCard lines={1} />
            <SkeletonCard lines={1} />
            <SkeletonCard lines={1} />
          </div>
          <div className="events">
            <div className="pane">
              <div className="event-list">
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard lines={2} />
              </div>
            </div>
            <div className="pane">
              <SkeletonCard lines={5} />
            </div>
          </div>
        </>
      )}

      {feed && !loading && !error && (
        <>
          {summary}
          <div className={cls('events', selected && (picked || !wide) && 'has-selected')}>
            <section className="pane events__list" aria-label="События">
              <div className="pane__head">
                <h2>События</h2>
                <label className="sort">
                  <span>Сортировка</span>
                  <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Сортировка событий">
                    <option value="relevance">По значимости</option>
                    <option value="date">По дате</option>
                  </select>
                </label>
              </div>

              <div className="list-tools">
                <label className="toggle">
                  <input type="checkbox" checked={showFiltered} onChange={(e) => setShowFiltered(e.target.checked)} />
                  <span className="toggle__ui" />
                  Показать отфильтрованные ({feed.filtered.length})
                </label>
                <span className="list-tools__stats">
                  Рассмотрено {feed.stats.news_considered} · не о бизнесе {feed.stats.filtered_non_business} · низкая значимость{' '}
                  {feed.stats.filtered_low_relevance} · обновлено {fmtDateTime(feed.generated_at)}
                </span>
              </div>

              {filter !== 'all' && (
                <div className="filter-note">
                  {FILTER_NOTE[filter]}.
                  <button className="link-btn" onClick={() => setFilter('all')}>
                    Показать все
                  </button>
                </div>
              )}

              <div className="event-list">
                {items.length === 0 && (
                  <EmptyState
                    title={feed.items.length ? 'Нет событий по выбранному фильтру' : 'Значимых событий для компании нет'}
                    text={feed.items.length ? 'Сбросьте фильтр, чтобы увидеть всю ленту.' : 'Новости за период не затрагивают профиль компании. Можно проверить свою новость.'}
                  />
                )}
                {items.map((it) => (
                  <EventCard key={it.news_id} item={it} selected={selected?.news_id === it.news_id} onSelect={() => setSelected(it.news_id)} />
                ))}
                {showFiltered && (
                  <>
                    <div className="sub-h">Отфильтровано — не показывается в ленте, с причиной</div>
                    {feed.filtered.length === 0 && <EmptyState title="Отфильтрованных публикаций нет" />}
                    {feed.filtered.map((it) => (
                      <EventCard key={it.news_id} item={it} filtered selected={selected?.news_id === it.news_id} onSelect={() => setSelected(it.news_id)} />
                    ))}
                  </>
                )}
              </div>
            </section>

            {selected ? (
              <EventDetail
                key={`${clientId}|${selected.news_id}`}
                item={selected}
                filtered={selectedIsFiltered}
                onBack={() => setSelected(null)}
              />
            ) : (
              <div className="pane detail empty-pane">
                <IconNews size={32} />
                <div className="strong">Выберите событие</div>
                <div className="small">Подробности и разбор для вашей компании появятся здесь.</div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
