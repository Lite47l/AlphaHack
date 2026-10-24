import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { useClient } from '../lib/context';
import { cls } from '../lib/format';
import { Modal, Notice, Spinner } from './ui';

export function CheckNewsModal({ onClose }: { onClose: () => void }) {
  const { href } = useClient();
  const nav = useNavigate();
  const [mode, setMode] = useState<'text' | 'url'>('text');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const sending = useRef(false);

  const urlOk = /^https?:\/\/[^\s]+\.[^\s]+/i.test(url.trim());
  const canSubmit = mode === 'text' ? text.trim().length > 0 : urlOk;

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    if (!canSubmit || sending.current) return;
    sending.current = true;
    setBusy(true);
    setErr(null);
    try {
      const body = mode === 'text' ? { title: title.trim() || undefined, text: text.trim() } : { url: url.trim(), title: title.trim() || undefined };
      const news = await api.createNews(body);
      onClose();
      nav(href(`/news/${news.id}`));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Не удалось добавить новость');
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Проверить свою новость"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn--secondary" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button className="btn btn--primary" onClick={() => submit()} disabled={!canSubmit || busy}>
            {busy && <Spinner size={14} />} Разобрать для компании
          </button>
        </>
      }
    >
      <p className="muted">
        Вставьте текст публикации или ссылку на неё — агент оценит значимость события для выбранного клиента и сформирует инсайт с
        источниками.
      </p>
      <div className="seg">
        <button className={cls('seg__btn', mode === 'text' && 'is-active')} onClick={() => setMode('text')} type="button">
          Текст новости
        </button>
        <button className={cls('seg__btn', mode === 'url' && 'is-active')} onClick={() => setMode('url')} type="button">
          Ссылка
        </button>
      </div>
      <form onSubmit={submit} className="form">
        <label className="field">
          <span>Заголовок {mode === 'url' && <span className="muted">(необязательно)</span>}</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Например: Минфин предложил изменить ставку НДС" maxLength={300} />
        </label>
        {mode === 'text' ? (
          <label className="field">
            <span>Текст</span>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} placeholder="Вставьте текст публикации" />
          </label>
        ) : (
          <label className="field">
            <span>Адрес публикации</span>
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." inputMode="url" />
            {url && !urlOk && <span className="field__err">Укажите адрес, начинающийся с http:// или https://</span>}
            <span className="muted small">Сервер сам загрузит страницу и извлечёт заголовок и текст.</span>
          </label>
        )}
        {err && <Notice tone="warn">{err}</Notice>}
      </form>
    </Modal>
  );
}
