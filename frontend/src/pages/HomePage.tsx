import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError, isAbort } from '../api/client';
import type { FeedItem } from '../api/types';
import { IconArrowRight, IconBank, IconNews, IconSpark } from '../components/Icons';
import { Chip, ErrorState, LevelBadge, Skeleton } from '../components/ui';
import { useClient, useFeed } from '../lib/context';
import { fmtBn, fmtRelative, plural } from '../lib/format';

// Демо-данные счетов: явно помечены, не связаны с реальным клиентом.
const DEMO_ACCOUNTS = [
  { name: 'Расчётный счёт ₽', num: '40702 810 •••• 0001', amount: '— ₽' },
  { name: 'Валютный счёт CNY', num: '40702 156 •••• 0002', amount: '— ¥' },
  { name: 'Депозит', num: 'Договор •••• 03', amount: '— ₽' },
];

export function HomePage() {
  const { client, clientId, href } = useClient();
  const { significant, loading: feedLoading, feed } = useFeed();
  const [top, setTop] = useState<FeedItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    setTop(null);
    setErr(null);
    if (!clientId) return;
    const ctrl = new AbortController();
    api
      .getFeed(clientId, { limit: 3 }, ctrl.signal)
      .then((f) => setTop(f.items))
      .catch((e) => {
        if (!isAbort(e)) setErr(e instanceof ApiError ? e.message : 'Ошибка загрузки');
      });
    return () => ctrl.abort();
  }, [clientId, nonce]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Добрый день!</h1>
          <p className="muted">
            {client ? (
              <>
                {client.display_name} · {client.subtitle}
              </>
            ) : (
              'Загрузка профиля клиента…'
            )}
          </p>
        </div>
      </div>

      <section className="news-entry" aria-label="Новости для вашего бизнеса">
        <div className="news-entry__head">
          <div className="news-entry__icon">
            <IconNews size={22} />
          </div>
          <div className="news-entry__title">
            <div className="news-entry__eyebrow">
              <IconSpark size={14} /> Персональная аналитика
            </div>
            <h2>Новости для вашего бизнеса</h2>
            <p>
              События, которые влияют на компанию: с объяснением «почему для вас», позицией аналитиков Альфа-Банка и ссылками на
              первоисточники.
            </p>
          </div>
          <div className="news-entry__count">
            {feedLoading || !feed ? (
              <Skeleton h={40} w={56} />
            ) : (
              <>
                <span className="news-entry__num">{significant}</span>
                <span className="news-entry__numlabel">
                  {plural(significant, 'значимое событие', 'значимых события', 'значимых событий')}
                </span>
              </>
            )}
          </div>
        </div>

        <div className="news-entry__list">
          {err && <ErrorState message={err} onRetry={() => setNonce((n) => n + 1)} />}
          {!err && !top && [0, 1, 2].map((i) => (
            <div key={i} className="mini-news">
              <Skeleton h={12} w="40%" />
              <Skeleton h={16} w="90%" />
              <Skeleton h={12} w="70%" />
            </div>
          ))}
          {top && top.length === 0 && <div className="muted">Значимых событий для компании за период нет.</div>}
          {top?.map((it) => (
            <Link key={it.news_id} to={href(`/news/${it.news_id}`)} className="mini-news">
              <div className="mini-news__meta">
                <LevelBadge level={it.relevance.level} short />
                <Chip>{it.event.event_label}</Chip>
                {it.bank_coverage.found && (
                  <Chip tone="red" icon={<IconBank size={12} />}>
                    позиция банка
                  </Chip>
                )}
                <span className="muted small">{fmtRelative(it.published_at)}</span>
              </div>
              <div className="mini-news__title">{it.title}</div>
              <div className="mini-news__why">
                <span className="why-label">Почему для вас:</span> {it.relevance.why_short}
              </div>
            </Link>
          ))}
        </div>
        <div className="news-entry__foot">
          <Link to={href('/news')} className="btn btn--primary">
            Открыть ленту <IconArrowRight size={16} />
          </Link>
          <Link to={href('/news?check=1')} className="btn btn--ghost-light">
            Проверить свою новость
          </Link>
        </div>
      </section>

      <div className="section-title">
        <h2>Счета</h2>
        <Chip tone="amber">демо-данные</Chip>
      </div>
      <div className="grid-3">
        {DEMO_ACCOUNTS.map((a) => (
          <div key={a.name} className="card card--pad account">
            <div className="account__name">{a.name}</div>
            <div className="account__num">{a.num}</div>
            <div className="account__amount">{a.amount}</div>
            <div className="muted small">Остатки в демо не отображаются</div>
          </div>
        ))}
      </div>
      {client && (
        <div className="card card--pad home-client">
          <div>
            <div className="muted small">Годовая выручка (из профиля)</div>
            <div className="strong">{fmtBn(client.revenue)}</div>
          </div>
          <div>
            <div className="muted small">Регион</div>
            <div className="strong">{client.region ?? 'не указан'}</div>
          </div>
          <div>
            <div className="muted small">Ключевые каналы влияния</div>
            <div className="chips">
              {client.top_channels.length ? client.top_channels.map((c) => <Chip key={c}>{c}</Chip>) : <span className="muted">—</span>}
            </div>
          </div>
          <Link to={href('/profile')} className="btn btn--secondary btn--sm">
            Профиль компании
          </Link>
        </div>
      )}
    </div>
  );
}
