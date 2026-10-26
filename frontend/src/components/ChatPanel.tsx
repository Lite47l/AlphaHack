import { useEffect, useRef, useState } from 'react';
import { api, ApiError, isAbort } from '../api/client';
import type { ChatMessage, SourceMap } from '../api/types';
import { cls, KIND_LABEL } from '../lib/format';
import { IconAlert, IconChat, IconSend } from './Icons';
import { Markers } from './sources';
import { Spinner } from './ui';

const PRESETS = [
  'Как это повлияет на обслуживание кредитов?',
  'Что это значит для наших поставщиков и покупателей?',
  'Покажи в разрезе рисков на 3–6 месяцев',
  'На чём основан вывод?',
];

interface Props {
  insightId: string | null;
  clientId: string;
  ready: boolean;
  onSources: (s: SourceMap) => void;
  /** Внутри панели события: без собственной карточки и заголовка */
  embedded?: boolean;
}

/** Чат уточнений. Компонент монтируется заново (key) при смене клиента/новости/инсайта. */
export function ChatPanel({ insightId, clientId, ready, onSources, embedded }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [histLoading, setHistLoading] = useState(false);
  const sending = useRef(false);
  const ctrlRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const onSourcesRef = useRef(onSources);
  onSourcesRef.current = onSources;

  useEffect(() => {
    if (!insightId || !ready) return;
    const ctrl = new AbortController();
    setHistLoading(true);
    api
      .getChat(insightId, clientId, ctrl.signal)
      .then((h) => {
        setMessages(h.messages);
        h.messages.forEach((m) => m.sources && onSourcesRef.current(m.sources));
        setHistLoading(false);
      })
      .catch((e) => {
        if (!isAbort(e)) setHistLoading(false);
      });
    return () => ctrl.abort();
  }, [insightId, clientId, ready]);

  useEffect(() => () => ctrlRef.current?.abort(), []);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, pending]);

  async function send(q: string) {
    const question = q.trim();
    if (!question || !insightId || !ready || sending.current) return;
    sending.current = true;
    setPending(question);
    setErr(null);
    setInput('');
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    try {
      const r = await api.postChat(insightId, clientId, question, ctrl.signal);
      if (r.message.sources) onSourcesRef.current(r.message.sources);
      const hist = r.history?.length ? r.history : [];
      const hasMsg = hist.some((m) => m.id === r.message.id);
      setMessages(
        hasMsg
          ? hist
          : [...(hist.length ? hist : messages), ...(hist.some((m) => m.role === 'user' && m.content === question) ? [] : [{ id: -Date.now(), role: 'user' as const, content: question, created_at: new Date().toISOString() }]), r.message],
      );
    } catch (e) {
      if (isAbort(e)) return;
      setErr(e instanceof ApiError ? e.message : 'Не удалось получить ответ');
      setInput(question);
    } finally {
      sending.current = false;
      setPending(null);
    }
  }

  return (
    <div className={cls('chat', !embedded && 'card')}>
      {!embedded && (
        <div className="chat__head">
          <IconChat size={18} />
          <div>
            <div className="strong">Уточняющие вопросы</div>
            <div className="muted small">Ответы опираются на этот инсайт и его источники</div>
          </div>
        </div>
      )}
      <div className="chat__list" ref={listRef}>
        {!ready && <div className="chat__empty">Чат станет доступен, когда инсайт будет готов.</div>}
        {ready && histLoading && (
          <div className="chat__empty">
            <Spinner size={14} /> Загрузка истории…
          </div>
        )}
        {ready && !histLoading && messages.length === 0 && !pending && (
          <div className="chat__empty">Задайте вопрос или выберите готовый ниже.</div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={cls('msg', `msg--${m.role}`)}>
            {m.role === 'assistant' && m.mode === 'rules' && <span className="kind kind--rules">ответ правилами — LLM недоступна</span>}
            <div className="msg__content">{m.content}</div>
            {m.statements && m.statements.length > 0 && (
              <ul className="msg__stmts">
                {m.statements.map((s, i) => (
                  <li key={i}>
                    <span className={cls('kind', `kind--${s.kind}`)}>{KIND_LABEL[s.kind] ?? s.kind}</span> {s.text}{' '}
                    <Markers ids={s.source_ids} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
        {pending && (
          <>
            <div className="msg msg--user">
              <div className="msg__content">{pending}</div>
            </div>
            <div className="msg msg--assistant msg--pending">
              <span className="typing">
                <span />
                <span />
                <span />
              </span>
              Агент ищет ответ в источниках…
            </div>
          </>
        )}
        {err && (
          <div className="chat__err">
            <IconAlert size={14} /> {err}
          </div>
        )}
      </div>
      <div className="chat__presets">
        {PRESETS.map((p) => (
          <button key={p} className="preset" disabled={!ready || !!pending} onClick={() => send(p)}>
            {p}
          </button>
        ))}
      </div>
      <form
        className="chat__form"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={ready ? 'Свой вопрос по событию…' : 'Ожидание инсайта…'}
          disabled={!ready || !!pending}
          maxLength={500}
        />
        <button className="btn btn--primary btn--icon" disabled={!ready || !!pending || !input.trim()} aria-label="Отправить">
          {pending ? <Spinner size={14} /> : <IconSend size={16} />}
        </button>
      </form>
    </div>
  );
}
