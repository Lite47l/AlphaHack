import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { USE_MOCKS } from '../api/client';
import { useClient, useFeed } from '../lib/context';
import { cls } from '../lib/format';
import { CompanySwitcher } from './CompanySwitcher';
import { IconCompare, IconCredit, IconHome, IconNews, IconProfile, IconPulse, IconSend, IconUsers, IconWallet } from './Icons';
import { ErrorState } from './ui';

export function Layout() {
  const { href, error, retry, client } = useClient();
  const { significant, loading } = useFeed();
  const loc = useLocation();
  const newsActive = loc.pathname.startsWith('/news');

  const nav = [
    { to: '/', label: 'Главная', icon: <IconHome />, end: true },
    { to: '/stub/accounts', label: 'Счета', icon: <IconWallet /> },
    { to: '/stub/payments', label: 'Платежи', icon: <IconSend /> },
    { to: '/stub/credits', label: 'Кредиты', icon: <IconCredit /> },
    { to: '/stub/salary', label: 'Зарплатный проект', icon: <IconUsers /> },
  ];

  return (
    <div className="app">
      <div className="header">
      <div className="demo-strip" role="note">
        Демонстрационный прототип, не действующий банк. Данные клиентов обезличены.
        {USE_MOCKS && <span className="demo-strip__mock">Моковые данные — бэкенд не используется</span>}
      </div>
      <header className="topbar">
        <NavLink to={href('/')} className="brand" aria-label="Альфа-Бизнес, главная">
          <span className="brand__mark">А</span>
          <span className="brand__text">
            Альфа-Бизнес<span className="brand__sub">Онлайн · демо</span>
          </span>
        </NavLink>
        <CompanySwitcher />
        <div className="topbar__spacer" />
        <div className="role">
          <span className="role__avatar">ФД</span>
          <span className="role__text">
            <span className="role__name">Финансовый директор</span>
            <span className="role__sub">роль: CFO</span>
          </span>
        </div>
      </header>
      </div>
      <div className="shell">
        <aside className="sidebar">
          <nav>
            {nav.map((n) => (
              <NavLink key={n.to} to={href(n.to)} end={n.end} className={({ isActive }) => cls('nav', isActive && 'is-active')}>
                {n.icon}
                <span>{n.label}</span>
              </NavLink>
            ))}
            <NavLink to={href('/news')} className={cls('nav', 'nav--feature', newsActive && 'is-active')}>
              <IconNews />
              <span>Новости для бизнеса</span>
              <span className={cls('nav__badge', loading && 'is-loading')} title="Значимые события (высокая и средняя значимость)">
                {loading ? '…' : significant}
              </span>
            </NavLink>
            <div className="nav-group">Аналитика клиента</div>
            <NavLink to={href('/profile')} className={({ isActive }) => cls('nav', isActive && 'is-active')}>
              <IconProfile />
              <span>Профиль компании</span>
            </NavLink>
            <NavLink to={href('/compare')} className={({ isActive }) => cls('nav', isActive && 'is-active')}>
              <IconCompare />
              <span>Сравнение значимости</span>
            </NavLink>
            <NavLink to={href('/monitoring')} className={({ isActive }) => cls('nav', isActive && 'is-active')}>
              <IconPulse />
              <span>Мониторинг качества</span>
            </NavLink>
          </nav>
          <div className="sidebar__foot">
            {client ? (
              <>
                <div className="muted small">Клиент</div>
                <div className="small strong">{client.company_id}</div>
              </>
            ) : null}
          </div>
        </aside>
        <main className="main">
          {error ? <ErrorState title="Список клиентов недоступен" message={error} onRetry={retry} /> : <Outlet />}
        </main>
      </div>
    </div>
  );
}
