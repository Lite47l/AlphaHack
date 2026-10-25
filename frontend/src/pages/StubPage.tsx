import { Link, useParams } from 'react-router-dom';
import { IconNews } from '../components/Icons';
import { useClient } from '../lib/context';

const TITLES: Record<string, string> = {
  accounts: 'Счета',
  payments: 'Платежи',
  credits: 'Кредиты',
  salary: 'Зарплатный проект',
};

export function StubPage() {
  const { section = '' } = useParams();
  const { href } = useClient();
  return (
    <div className="page">
      <div className="page-head">
        <h1>{TITLES[section] ?? 'Раздел'}</h1>
      </div>
      <div className="card card--pad stub">
        <p>Раздел не входит в демонстрационный прототип.</p>
        <Link to={href('/news')} className="btn btn--primary">
          <IconNews size={16} /> Перейти к новостям для бизнеса
        </Link>
      </div>
    </div>
  );
}

export function NotFoundPage() {
  const { href } = useClient();
  return (
    <div className="page">
      <div className="card card--pad stub">
        <h1>Страница не найдена</h1>
        <Link to={href('/')} className="btn btn--secondary">
          На главную
        </Link>
      </div>
    </div>
  );
}
