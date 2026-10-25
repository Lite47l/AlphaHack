import { useEffect, type ReactNode } from 'react';
import type { Level } from '../api/types';
import { cls, LEVEL_LABEL, LEVEL_SHORT } from '../lib/format';
import { IconAlert, IconClose, IconInfo } from './Icons';

export function LevelBadge({ level, short }: { level: Level; short?: boolean }) {
  return (
    <span className={cls('level', `level--${level}`)}>
      <span className="level__dot" />
      {short ? LEVEL_SHORT[level] : LEVEL_LABEL[level]}
    </span>
  );
}

export function ScoreBar({ score, level, wide }: { score: number; level: Level; wide?: boolean }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  return (
    <div className={cls('score', wide && 'score--wide')} title={`Оценка значимости: ${score.toFixed(2)} из 1`}>
      <div className="score__track">
        <div className={cls('score__fill', `score__fill--${level}`)} style={{ width: `${pct}%` }} />
        <span className="score__tick" style={{ left: '18%' }} />
        <span className="score__tick" style={{ left: '30%' }} />
        <span className="score__tick" style={{ left: '45%' }} />
      </div>
      <span className="score__num">{score.toFixed(2)}</span>
    </div>
  );
}

export function Chip({
  children,
  tone = 'neutral',
  icon,
  title,
}: {
  children: ReactNode;
  tone?: 'neutral' | 'red' | 'green' | 'violet' | 'amber' | 'blue' | 'dark';
  icon?: ReactNode;
  title?: string;
}) {
  return (
    <span className={cls('chip', `chip--${tone}`)} title={title}>
      {icon}
      {children}
    </span>
  );
}

export function Skeleton({ h = 14, w = '100%', r = 6 }: { h?: number; w?: number | string; r?: number }) {
  return <span className="skeleton" style={{ height: h, width: w, borderRadius: r }} />;
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="card card--pad skeleton-card" aria-busy="true">
      <Skeleton h={12} w="30%" />
      <Skeleton h={20} w="85%" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} h={12} w={`${90 - i * 12}%`} />
      ))}
    </div>
  );
}

export function ErrorState({ title = 'Не удалось загрузить данные', message, onRetry }: { title?: string; message?: string | null; onRetry?: () => void }) {
  return (
    <div className="state state--error" role="alert">
      <IconAlert size={22} />
      <div>
        <div className="state__title">{title}</div>
        {message && <div className="state__text">{message}</div>}
      </div>
      {onRetry && (
        <button className="btn btn--secondary btn--sm" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, text, action }: { title: string; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state state--empty">
      <IconInfo size={22} />
      <div>
        <div className="state__title">{title}</div>
        {text && <div className="state__text">{text}</div>}
      </div>
      {action}
    </div>
  );
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'warn' | 'violet'; children: ReactNode }) {
  return (
    <div className={cls('notice', `notice--${tone}`)}>
      {tone === 'warn' ? <IconAlert size={16} /> : <IconInfo size={16} />}
      <div>{children}</div>
    </div>
  );
}

export function useEscape(onClose: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose, active]);
}

export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  useEscape(onClose);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal__head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть">
            <IconClose />
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-label="Загрузка" />;
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="section-title">
      <h2>{children}</h2>
      {aside}
    </div>
  );
}
