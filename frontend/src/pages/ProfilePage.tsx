import { useEffect, useState } from 'react';
import { api, ApiError, isAbort } from '../api/client';
import type { CompanyProfile, PaymentsAggregate, ShareItem } from '../api/types';
import { IconAlert, IconGraph, IconProfile } from '../components/Icons';
import { Chip, ErrorState, Notice, SectionTitle, SkeletonCard } from '../components/ui';
import { useClient } from '../lib/context';
import { cls, fmtBn, fmtMoneyShort, fmtNum, fmtPct, fmtValue } from '../lib/format';

function Bars({ items, empty = 'нет данных' }: { items: ShareItem[]; empty?: string }) {
  if (!items?.length) return <div className="muted small">{empty}</div>;
  const max = Math.max(0.0001, ...items.map((x) => x.share));
  return (
    <div className="bars">
      {items.map((x) => (
        <div className="bar" key={x.key}>
          <span className="bar__label" title={x.label}>
            {x.label}
          </span>
          <span className="bar__track">
            <span style={{ width: `${(x.share / max) * 100}%` }} />
          </span>
          <span className="bar__val">{fmtPct(x.share, 1)}</span>
        </div>
      ))}
    </div>
  );
}

function Payments({ title, p }: { title: string; p?: PaymentsAggregate | null }) {
  if (!p) {
    return (
      <div className="card card--pad">
        <h3>{title}</h3>
        <div className="muted">Нет данных о платежах.</div>
      </div>
    );
  }
  return (
    <div className="card card--pad payments">
      <h3>{title}</h3>
      <div className="kpis kpis--4 kpis--compact">
        <div className="kpi">
          <div className="kpi__label">Объём</div>
          <div className="kpi__value">{fmtMoneyShort(p.amount)}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Платежей</div>
          <div className="kpi__value">{fmtNum(p.count)}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Контрагентов</div>
          <div className="kpi__value">{fmtNum(p.counterparties)}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Доля топ-5</div>
          <div className="kpi__value">{fmtPct(p.top5_share)}</div>
        </div>
      </div>
      <div className="muted small">
        Крупнейший контрагент: {fmtPct(p.max_share)} · без профиля в выборке: {fmtPct(p.unknown_profile_share)} объёма
      </div>
      <div className="grid-3 grid-3--tight">
        <div>
          <div className="sub-h">Отрасли контрагентов</div>
          <Bars items={p.sectors} />
        </div>
        <div>
          <div className="sub-h">Регионы контрагентов</div>
          <Bars items={p.regions} />
        </div>
        <div>
          <div className="sub-h">Страны ФТС контрагентов</div>
          <Bars items={p.fts_countries} />
        </div>
      </div>
      {p.top?.length > 0 && (
        <>
          <div className="sub-h">Топ контрагентов</div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Контрагент</th>
                  <th className="num">Сумма</th>
                  <th className="num">Платежей</th>
                  <th className="num">Доля</th>
                  <th>ОКВЭД</th>
                  <th>Регион</th>
                </tr>
              </thead>
              <tbody>
                {p.top.map((c) => (
                  <tr key={c.company_id}>
                    <td>
                      <code>{c.company_id}</code> {c.in_profile && <Chip tone="green">в выборке</Chip>}
                    </td>
                    <td className="num">{fmtMoneyShort(c.amt)}</td>
                    <td className="num">{fmtNum(c.cnt)}</td>
                    <td className="num">{fmtPct(c.share, 1)}</td>
                    <td className="small">{c.okved_code ? `${c.okved_code} ${c.okved_name ?? ''}` : <span className="muted">нет данных</span>}</td>
                    <td className="small">{c.region ?? <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export function ProfilePage() {
  const { clientId } = useClient();
  const [p, setP] = useState<CompanyProfile | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    setP(null);
    setErr(null);
    if (!clientId) return;
    const ctrl = new AbortController();
    api
      .getCompany(clientId, ctrl.signal)
      .then(setP)
      .catch((e) => !isAbort(e) && setErr(e instanceof ApiError ? e.message : 'Ошибка'));
    return () => ctrl.abort();
  }, [clientId, nonce]);

  if (err) return <div className="page"><ErrorState message={err} onRetry={() => setNonce((n) => n + 1)} /></div>;
  if (!p) {
    return (
      <div className="page">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={6} />
      </div>
    );
  }
  const s = p.summary;
  const d = p.derived;
  return (
    <div className="page page--wide">
      <div className="page-head">
        <div>
          <h1>
            {s.display_name}{' '}
            {s.completeness === 'incomplete' && <span className="badge-incomplete badge-incomplete--lg">неполный профиль</span>}
          </h1>
          <p className="muted">{s.subtitle}</p>
          <div className="chips">
            <Chip>ОКВЭД {s.okved_code ?? '—'}</Chip>
            <Chip>{s.region ?? 'регион не указан'}</Chip>
            <Chip>Выручка {fmtBn(s.revenue)}</Chip>
            {s.sectors.map((x) => (
              <Chip key={x.key} tone="dark">
                {x.label}
              </Chip>
            ))}
            {s.profile_status === 'ambiguous' && <Chip tone="amber">профиль сопоставлен неоднозначно</Chip>}
          </div>
        </div>
      </div>

      {(p.missing_fields.length > 0 || s.key_missing.length > 0) && (
        <Notice tone="warn">
          Нет данных по полям: {[...new Set([...s.key_missing, ...p.missing_fields])].map((f) => (
            <code key={f} className="code-inline">
              {f}
            </code>
          ))}
          . Компоненты оценки, зависящие от них, не начисляются.
        </Notice>
      )}

      <SectionTitle aside={<Chip tone="neutral" icon={<IconGraph size={12} />}>вычислено</Chip>}>Каналы чувствительности</SectionTitle>
      <div className="channels">
        {p.channels.length === 0 && <div className="muted">Каналы не определены.</div>}
        {p.channels.map((c) => (
          <div key={c.key} className="card card--pad channel">
            <div className="channel__head">
              <span className="strong">{c.label}</span>
              <span className="channel__strength">{fmtPct(c.strength)}</span>
            </div>
            <div className="bar__track bar__track--lg">
              <span style={{ width: `${c.strength * 100}%` }} />
            </div>
            <ul className="plain-list small">
              {c.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
            <div className="evidence">
              {c.basis.map((b) => (
                <code key={b} className={b.startsWith('P:') ? 'ev-p' : 'ev-g'}>
                  {b}
                </code>
              ))}
            </div>
          </div>
        ))}
      </div>

      <SectionTitle aside={<Chip tone="green" icon={<IconProfile size={12} />}>прямые наблюдения</Chip>}>Данные о компании</SectionTitle>
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Поле</th>
              <th>Значение</th>
              <th>Источник</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(p.observed).map(([k, f]) => (
              <tr key={k} className={cls(f.value === null && 'is-missing')}>
                <td>
                  <div className="strong">{f.title}</div>
                  <code className="muted small">P:{k}</code>
                </td>
                <td>{f.value === null ? <span className="muted">нет данных</span> : fmtValue(f.value, k)}</td>
                <td className="small muted">{f.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SectionTitle aside={<Chip tone="neutral" icon={<IconGraph size={12} />}>вычислено</Chip>}>Вычисленные признаки</SectionTitle>
      <div className="grid-2">
        <div className="card card--pad">
          <h3>Позиция по выручке в классе ОКВЭД</h3>
          {d.revenue_rank ? (
            <>
              <div className="value-big">
                {d.revenue_rank.rank} из {fmtNum(d.revenue_rank.of)}
              </div>
              <div className="muted small">Класс ОКВЭД {d.revenue_rank.okved_class}</div>
              <div className="notice notice--info small">
                <IconAlert size={14} />
                <div>{d.revenue_rank.note || 'Место среди компаний выборки — не доля рынка.'}</div>
              </div>
            </>
          ) : (
            <div className="muted">нет данных</div>
          )}
        </div>
        <div className="card card--pad">
          <h3>Группа компаний</h3>
          {d.group ? (
            <>
              <div className="value-big">{d.group.size} комп.</div>
              <div className="muted small">
                <code>{d.group.group_id}</code> · суммарная выручка участников {fmtBn(d.group.revenue_sum)}
              </div>
              <div className="chips">
                {d.group.member_sectors.map((m) => (
                  <Chip key={m.key}>
                    {m.label}
                    {m.companies ? ` · ${m.companies}` : ''}
                  </Chip>
                ))}
              </div>
              <div className="muted small">{d.group.note}</div>
            </>
          ) : (
            <div className="muted">Компания не входит в группу (по данным выборки).</div>
          )}
        </div>
      </div>

      <div className="stack">
        <Payments title="Исходящие платежи (поставщики)" p={d.payments_out} />
        <Payments title="Входящие платежи (покупатели)" p={d.payments_in} />
      </div>

      {d.persons && (
        <div className="card card--pad">
          <h3>Связанные физлица</h3>
          <div>Связанных физлиц: {fmtNum(d.persons.linked_persons)}</div>
          {d.persons.companies_via_shared_persons?.length > 0 && (
            <div className="muted small">Компаний через общих физлиц: {d.persons.companies_via_shared_persons.length}</div>
          )}
          <div className="muted small">{d.persons.note}</div>
        </div>
      )}

      {p.data_notes.length > 0 && (
        <div className="card card--pad">
          <h3>Примечания к данным</h3>
          <ul className="plain-list">
            {p.data_notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
