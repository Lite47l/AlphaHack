import { NavLink, Outlet, useLocation, useSearchParams } from 'react-router-dom';
import { USE_MOCKS } from '../api/client';
import { useClient, useFeed } from '../lib/context';
import { cls } from '../lib/format';
import { CheckNewsModal } from './CheckNewsModal';
import { CompanySwitcher } from './CompanySwitcher';
import { IconCompare, IconDoc, IconHome, IconNews, IconProfile, IconPulse, IconSpark } from './Icons';
import { ErrorState } from './ui';

export function Layout() {
  const { href, error, retry, client } = useClient();
  const { significant, loading } = useFeed();
  const loc = useLocation();
  const [params, setParams] = useSearchParams();
  const eventsActive = loc.pathname.startsWith('/news');
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

  const link = ({ isActive }: { isActive: boolean }) => cls('nav', isActive && 'is-active');

  return (
    <div className="app">
      <aside className="sidebar">
        <div>
          <NavLink to={href('/')} className="brand" aria-label="Альфа Бизнес, обзор">
            <span className="brand__mark">А</span>
            <span className="brand__text">
              Альфа Бизнес <span className="brand__tag">Демо</span>
            </span>
          </NavLink>
          <nav aria-label="Основная навигация">
            <NavLink to={href('/')} end className={link}>
              <IconHome size={20} />
              <span>Обзор</span>
            </NavLink>
            <NavLink to={href('/news')} className={() => cls('nav', eventsActive && 'is-active')}>
              <IconNews size={20} />
              <span>События</span>
              <span className={cls('nav__badge', loading && 'is-loading')} title="Значимые события: высокая и средняя значимость">
                {loading ? '…' : significant}
              </span>
            </NavLink>
            <NavLink to={href('/profile')} className={link}>
              <IconProfile size={20} />
              <span>Профиль компании</span>
            </NavLink>
            <NavLink to={href('/sources')} className={link}>
              <IconDoc size={20} />
              <span>Источники</span>
            </NavLink>
            <NavLink to={href('/monitoring')} className={link}>
              <IconPulse size={20} />
              <span>Качество</span>
            </NavLink>
            <div className="nav-group">Дополнительно</div>
            <NavLink to={href('/compare')} className={({ isActive }) => cls('nav', 'nav--sub', isActive && 'is-active')}>
              <IconCompare size={18} />
              <span>Сравнение значимости</span>
            </NavLink>
          </nav>
        </div>
        <div className="sidebar__foot">
          Демонстрационный прототип. Данные обезличены.
          {USE_MOCKS && <div className="sidebar__mock">Моковые данные — бэкенд не используется</div>}
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <CompanySwitcher />
          {client?.subtitle ? (
            <div className="topbar__industry" title={client.subtitle}>
              {client.subtitle}
            </div>
          ) : (
            <div className="topbar__spacer" />
          )}
          <div className="role">
            <span className="role__avatar" aria-hidden="true">
              ИФ
            </span>
            <span className="role__text">
              <span className="role__name">Имя Фамилия</span>
              <span className="role__sub">Финансовый директор</span>
            </span>
          </div>
          <button className="btn btn--primary" onClick={() => setCheck(true)}>
            <IconSpark size={16} /> Проверить новость
          </button>
        </header>
        <main className="main">
          {error ? <ErrorState title="Список клиентов недоступен" message={error} onRetry={retry} /> : <Outlet />}
        </main>
      </div>

      {checkOpen && <CheckNewsModal onClose={() => setCheck(false)} />}
    </div>
  );
}
