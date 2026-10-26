import { useEffect, useState } from 'react';

/** Подписка на media query; нужна, чтобы решить, автоматически ли открывать первое событие (на узком экране — нет). */
export function useMediaQuery(query: string): boolean {
  const get = () => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : true);
  const [match, setMatch] = useState(get);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const h = () => setMatch(mq.matches);
    h();
    mq.addEventListener('change', h);
    return () => mq.removeEventListener('change', h);
  }, [query]);
  return match;
}
