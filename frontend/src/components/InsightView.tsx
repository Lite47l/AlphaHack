import type { ReactNode } from 'react';
import type { Insight, Statement } from '../api/types';
import { cls, CONFIDENCE_LABEL, fmtDate, fmtDateTime, KIND_LABEL } from '../lib/format';
import { IconAlert, IconBank, IconBrain, IconDoc, IconExternal, IconInfo, IconNews, IconProfile, IconSpark } from './Icons';
import { FeatureChips, Markers, useSources } from './sources';
import { Chip, LevelBadge, ScoreBar } from './ui';

/** Содержимое блока «Позиция Альфа-Банка»: цитаты с документом и страницей либо сообщение, что материал не найден. */
export function BankBody({ bv }: { bv: Insight['bank_view'] }) {
  const reg = useSources();
  return (
    <>
    {bv.status === 'not_found' || bv.statements.length === 0 ? (
      <div className="bank-empty">
        <IconInfo size={16} />
        <div>
          <div className="strong">Позиция банка по этой теме не найдена.</div>
          <div className="muted small">{bv.note || 'В корпусе аналитики Альфа-Банка нет материалов по теме события. Выводы ниже не опираются на мнение банка.'}</div>
        </div>
      </div>
    ) : (
      <>
        {bv.note && <div className="block__hint">{bv.note}</div>}
        {bv.statements.map((b, i) => {
          const src = b.source_ids.map((id) => reg.get(id)).find((s) => s?.type === 'bank');
          const url = b.url || (src && src.type === 'bank' ? src.url : undefined);
          return (
            <div key={i} className="bank-stmt">
              <p className="bank-stmt__text">
                {b.text} <Markers ids={b.source_ids} />
              </p>
              {b.quote && (
                <blockquote className="bank-quote">
                  <span className="bank-quote__mark">«</span>
                  {b.quote}
                  <span className="bank-quote__mark">»</span>
                </blockquote>
              )}
              <div className="bank-stmt__doc">
                <IconDoc size={14} />
                <span className="strong">{b.doc_title}</span>
                {b.page != null && <span>· стр. {b.page}</span>}
                {b.published_at && <span>· {fmtDate(b.published_at)}</span>}
                {url && (
                  <a href={url} target="_blank" rel="noreferrer" className="link">
                    открыть документ <IconExternal size={12} />
                  </a>
                )}
              </div>
              {b.warning && (
                <div className="feed-card__warn">
                  <IconAlert size={14} /> {b.warning}
                </div>
              )}
            </div>
          );
        })}
      </>
    )}
    </>
  );
}

function KindBadge({ kind }: { kind: Statement['kind'] }) {
  return <span className={cls('kind', `kind--${kind}`)}>{KIND_LABEL[kind] ?? kind}</span>;
}

export function StatementList({ items, showKind, features }: { items: Statement[]; showKind?: boolean; features?: boolean }) {
  return (
    <ul className="stmts">
      {items.map((s, i) => (
        <li key={i} className={cls('stmt', `stmt--${s.kind}`)}>
          <div className="stmt__text">
            {showKind && <KindBadge kind={s.kind} />}
            {s.text} <Markers ids={s.source_ids} />
          </div>
          {features && <FeatureChips ids={s.source_ids} />}
          {s.confidence && s.confidence !== 'high' && (
            <span className="stmt__conf">уверенность: {CONFIDENCE_LABEL[s.confidence]}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function Block({
  title,
  icon,
  badge,
  tone,
  children,
  hint,
}: {
  title: string;
  icon?: ReactNode;
  badge?: ReactNode;
  tone?: 'fact' | 'link' | 'bank' | 'ai' | 'neutral' | 'risk' | 'opp' | 'limit';
  children: ReactNode;
  hint?: string;
}) {
  return (
    <section className={cls('block', tone && `block--${tone}`)}>
      <div className="block__head">
        {icon && <span className="block__icon">{icon}</span>}
        <h3>{title}</h3>
        {badge}
      </div>
      {hint && <div className="block__hint">{hint}</div>}
      {children}
    </section>
  );
}

const ACTION_KIND: Record<string, string> = { action: 'Действие', question: 'Вопрос менеджеру / команде', scenario: 'Сценарий' };

export function InsightView({ insight }: { insight: Insight }) {
  const rel = insight.relevance;
  const bv = insight.bank_view;
  const rules = insight.mode === 'rules';
  const issues = insight.validation?.issues ?? [];

  return (
    <div className="insight">
      <header className="insight__head card card--pad">
        <div className="insight__badges">
          <LevelBadge level={rel.level} />
          <Chip tone="dark">{insight.event.event_label}</Chip>
          {rules ? (
            <Chip tone="amber" icon={<IconAlert size={12} />}>
              Сформировано правилами — LLM недоступна
            </Chip>
          ) : (
            <Chip tone="violet" icon={<IconBrain size={12} />}>
              LLM-агент
            </Chip>
          )}
          <span className="muted small">общая уверенность: {CONFIDENCE_LABEL[insight.confidence]}</span>
        </div>
        <h2 className="insight__headline">{insight.headline}</h2>
        <div className="insight__score">
          <ScoreBar score={rel.score} level={rel.level} wide />
          <span className="muted small">{rel.why_short}</span>
        </div>
        {rel.profile_warnings.length > 0 && (
          <div className="feed-card__warn">
            <IconAlert size={14} /> {rel.profile_warnings.join('; ')}
          </div>
        )}
      </header>

      <Block title="Что произошло" icon={<IconNews size={16} />} tone="fact" badge={<span className="kind kind--fact">Факт из новости</span>}>
        <StatementList items={insight.what_happened} />
      </Block>

      <Block
        title="Почему это важно для компании"
        icon={<IconProfile size={16} />}
        tone="link"
        badge={<span className="kind kind--client_link">Данные о клиенте</span>}
        hint="Признаки клиента кликабельны: видно поле, значение и откуда оно взято."
      >
        {insight.why_it_matters.length ? (
          <StatementList items={insight.why_it_matters} features />
        ) : (
          <p className="muted">Связь с профилем компании не установлена.</p>
        )}
      </Block>

      <section className="block block--bank">
        <div className="block__head">
          <span className="block__icon">
            <IconBank size={16} />
          </span>
          <h3>Позиция Альфа-Банка</h3>
          <span className="badge-bank">Аналитика Альфа-Банка</span>
          {bv.status === 'outdated' && <Chip tone="amber">материал устарел</Chip>}
        </div>
        <BankBody bv={bv} />
      </section>

      <Block
        title="Выводы AI"
        icon={<IconSpark size={16} />}
        tone="ai"
        badge={
          rules ? (
            <span className="kind kind--rules">Сформировано правилами — LLM недоступна</span>
          ) : (
            <span className="kind kind--ai_conclusion">Вывод AI</span>
          )
        }
        hint="Интерпретация модели на основе фактов, профиля и аналитики банка. Не является позицией банка."
      >
        {insight.ai_conclusions.length ? <StatementList items={insight.ai_conclusions} /> : <p className="muted">Выводов нет.</p>}
      </Block>

      <div className="grid-2">
        <Block title="Риски" tone="risk">
          {insight.risks.length ? <StatementList items={insight.risks} showKind /> : <p className="muted">Рисков не выявлено.</p>}
        </Block>
        <Block title="Возможности" tone="opp">
          {insight.opportunities.length ? (
            <StatementList items={insight.opportunities} showKind />
          ) : (
            <p className="muted">Возможностей не выявлено.</p>
          )}
        </Block>
      </div>

      <Block title="Что можно сделать" tone="neutral">
        {insight.actions.length ? (
          <ul className="actions">
            {insight.actions.map((a, i) => (
              <li key={i} className={cls('action', `action--${a.kind}`)}>
                <span className={cls('action__type', `kind kind--${a.kind}`)}>{ACTION_KIND[a.kind] ?? KIND_LABEL[a.kind]}</span>
                <span>
                  {a.text} <Markers ids={a.source_ids} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Рекомендаций нет.</p>
        )}
        {insight.bank_offer && (
          <div className="offer">
            <span className="offer__label">Предложение банка</span>
            <div>
              <div className="strong">{insight.bank_offer.product}</div>
              <div>
                {insight.bank_offer.text} <Markers ids={insight.bank_offer.source_ids} />
              </div>
            </div>
          </div>
        )}
      </Block>

      <Block title="Ограничения и неопределённость" icon={<IconAlert size={16} />} tone="limit">
        <div className="limits">
          <div className="limits__row">
            <span className="muted">Уверенность:</span> <strong>{CONFIDENCE_LABEL[insight.confidence]}</strong>
            <span className="muted">· Проверка:</span>{' '}
            {insight.validation?.passed ? (
              <Chip tone="green">пройдена</Chip>
            ) : (
              <Chip tone="red">не пройдена</Chip>
            )}
            {insight.validation?.repairs > 0 && <span className="muted small">доработок: {insight.validation.repairs}</span>}
          </div>
          {insight.limitations.length > 0 && (
            <ul className="plain-list">
              {insight.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          )}
          {issues.length > 0 && (
            <div className="issues">
              <div className="muted small strong">Замечания валидатора</div>
              {issues.map((x, i) => (
                <div key={i} className={cls('issue', `issue--${x.severity}`)}>
                  <code>{x.code}</code> <span>{x.message}</span> <span className="muted small">{x.path}</span>
                </div>
              ))}
            </div>
          )}
          <div className="muted small">
            Модели:{' '}
            {Object.entries(insight.models ?? {})
              .filter(([, v]) => v)
              .map(([k, v]) => `${k}: ${v}`)
              .join(', ') || 'не использовались'}{' '}
            · версия промпта {insight.prompt_version}
          </div>
        </div>
      </Block>

      {insight.related_news.length > 0 && (
        <Block title="Также сообщают" tone="neutral">
          <ul className="related">
            {insight.related_news.map((r) => (
              <li key={r.news_id}>
                <span className="strong">{r.source_name}</span>
                <span>{r.title}</span>
                <span className="muted small">{fmtDateTime(r.published_at)}</span>
                {r.url && (
                  <a href={r.url} target="_blank" rel="noreferrer" className="ext">
                    <IconExternal size={12} />
                  </a>
                )}
              </li>
            ))}
          </ul>
        </Block>
      )}
    </div>
  );
}
