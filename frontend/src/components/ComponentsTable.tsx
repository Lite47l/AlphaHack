import type { Relevance } from '../api/types';
import { fmtPct } from '../lib/format';

/** Из чего сложилась оценка значимости: компоненты, вклад и признаки профиля, на которых они основаны. */
export function ComponentsTable({ relevance: r }: { relevance: Relevance }) {
  const maxContribution = Math.max(0.0001, ...r.components.map((c) => c.weight));
  if (r.components.length === 0) return <p className="muted small">Детализация оценки недоступна.</p>;
  return (
    <div className="components">
      <div className="table-wrap">
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
      </div>
      <p className="muted small" style={{ marginTop: 8 }}>
        Итоговая оценка значимости: {r.score.toFixed(2)} из 1 · уверенность: {r.confidence === 'high' ? 'высокая' : r.confidence === 'medium' ? 'средняя' : 'низкая'}
      </p>
    </div>
  );
}
