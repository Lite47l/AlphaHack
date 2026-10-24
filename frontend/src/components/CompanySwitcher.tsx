import { useEffect, useRef, useState } from 'react';
import { api, isAbort } from '../api/client';
import type { CompanySummary } from '../api/types';
import { useClient } from '../lib/context';
import { cls, fmtBn } from '../lib/format';
import { IconBank, IconCheck, IconChevron, IconSearch } from './Icons';
import { Spinner } from './ui';

export function CompanySwitcher() {
  const { client, clientId, companies, companiesTotal, setClient, loading } = useClient();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [items, setItems] = useState<CompanySummary[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const k = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', h);
    document.addEventListener('keydown', k);
    setTimeout(() => input.current?.focus(), 0);
    return () => {
      document.removeEventListener('mousedown', h);
      document.removeEventListener('keydown', k);
    };
  }, [open]);

  // Поиск на сервере с задержкой и отменой предыдущего запроса
  useEffect(() => {
    if (!open) return;
    if (!q.trim()) {
      setItems(null);
      setErr(null);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      setBusy(true);
      api
        .listCompanies(q.trim(), ctrl.signal)
        .then((r) => {
          setItems(r.items);
          setErr(null);
          setBusy(false);
        })
        .catch((e) => {
          if (isAbort(e)) return;
          setErr(e.message);
          setBusy(false);
        });
    }, 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q, open]);

  const list = items ?? companies;

  return (
    <div className="switcher" ref={root}>
      <button className={cls('switcher__btn', open && 'is-open')} onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}>
        <span className="switcher__avatar">
          <IconBank size={18} />
        </span>
        <span className="switcher__text">
          <span className="switcher__name">
            {client?.display_name ?? (loading ? 'Загрузка клиентов…' : clientId ?? 'Клиент не выбран')}
            {client?.completeness === 'incomplete' && <span className="badge-incomplete">неполный профиль</span>}
          </span>
          <span className="switcher__sub">{client ? `${client.subtitle}` : 'Выберите компанию'}</span>
        </span>
        <IconChevron size={16} />
      </button>
      {open && (
        <div className="switcher__pop" role="listbox">
          <div className="switcher__search">
            <IconSearch size={16} />
            <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="ID, отрасль или регион" />
            {busy && <Spinner size={14} />}
          </div>
          <div className="switcher__hint">
            {items ? `Найдено: ${items.length}` : `Клиенты (${companies.length}${companiesTotal > companies.length ? ` из ${companiesTotal}` : ''})`}
          </div>
          {err && <div className="switcher__err">{err}</div>}
          <div className="switcher__list">
            {list.length === 0 && !busy && <div className="switcher__empty">Ничего не найдено</div>}
            {list.map((c) => (
              <button
                key={c.company_id}
                className={cls('switcher__item', c.company_id === clientId && 'is-active')}
                onClick={() => {
                  setClient(c);
                  setOpen(false);
                  setQ('');
                }}
                role="option"
                aria-selected={c.company_id === clientId}
              >
                <div className="switcher__row">
                  <span className="switcher__iname">{c.display_name}</span>
                  {c.completeness === 'incomplete' && <span className="badge-incomplete">неполный профиль</span>}
                  {c.company_id === clientId && <IconCheck size={16} className="switcher__check" />}
                </div>
                <div className="switcher__isub">{c.subtitle}</div>
                <div className="switcher__meta">
                  <span>{c.region ?? 'регион не указан'}</span>
                  <span>·</span>
                  <span>{fmtBn(c.revenue)}</span>
                  {c.okved_code && (
                    <>
                      <span>·</span>
                      <span>ОКВЭД {c.okved_code}</span>
                    </>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
