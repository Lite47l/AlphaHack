import { useState } from 'react';
import type { ProgressStep, Trace, TraceStep } from '../api/types';
import { cls, fmtMs, fmtNum, STEP_KIND_LABEL, STEP_STATUS_LABEL } from '../lib/format';
import { IconBrain, IconCheck, IconChevron, IconClose, IconFlag, IconPlan, IconRepair, IconShield, IconTool } from './Icons';
import { Markers } from './sources';
import { Chip, Spinner } from './ui';

export function kindIcon(kind: string, size = 16) {
  switch (kind) {
    case 'plan':
      return <IconPlan size={size} />;
    case 'tool':
      return <IconTool size={size} />;
    case 'llm':
      return <IconBrain size={size} />;
    case 'check':
    case 'validate':
      return <IconShield size={size} />;
    case 'repair':
      return <IconRepair size={size} />;
    case 'final':
      return <IconFlag size={size} />;
    default:
      return <IconTool size={size} />;
  }
}

function StatusDot({ status }: { status: string }) {
  if (status === 'running') return <Spinner size={14} />;
  if (status === 'ok') return <IconCheck size={14} />;
  if (status === 'error') return <IconClose size={14} />;
  return <span className="dot" />;
}

/** Живой список шагов агента, пока инсайт формируется. */
export function AgentProgress({ steps, status, newsTitle }: { steps: ProgressStep[]; status: string; newsTitle?: string }) {
  const lastIdx = steps.length - 1;
  return (
    <div className="card agent">
      <div className="agent__head">
        <div className="agent__pulse">
          <IconBrain size={22} />
        </div>
        <div>
          <div className="agent__title">{status === 'queued' ? 'Задача поставлена в очередь' : 'AI-агент анализирует событие'}</div>
          <div className="muted small">
            {newsTitle ? `«${newsTitle}» — ` : ''}составляет план, вызывает инструменты, проверяет ссылки и цифры.
          </div>
        </div>
      </div>
      <ol className="timeline">
        {steps.length === 0 && (
          <li className="tl tl--running">
            <span className="tl__icon">
              <Spinner size={14} />
            </span>
            <div className="tl__body">
              <div className="tl__title">Подготовка контекста…</div>
            </div>
          </li>
        )}
        {steps.map((s, i) => {
          const running = s.status === 'running' || (i === lastIdx && status === 'processing' && !['ok', 'error', 'empty', 'skipped'].includes(s.status));
          return (
            <li key={`${s.step}-${i}`} className={cls('tl', `tl--${running ? 'running' : s.status}`, `tl--k-${s.kind}`)}>
              <span className="tl__icon">{kindIcon(s.kind)}</span>
              <div className="tl__body">
                <div className="tl__title">
                  {s.title}
                  <span className="tl__kind">{STEP_KIND_LABEL[s.kind] ?? s.kind}</span>
                </div>
                <code className="tl__name">{s.name}</code>
              </div>
              <span className={cls('tl__status', `st--${running ? 'running' : s.status}`)}>
                <StatusDot status={running ? 'running' : s.status} />
                {STEP_STATUS_LABEL[running ? 'running' : s.status] ?? s.status}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function TraceStepCard({ s }: { s: TraceStep }) {
  const [open, setOpen] = useState(false);
  const hasInput = s.input !== null && s.input !== undefined && !(typeof s.input === 'object' && Object.keys(s.input as object).length === 0);
  return (
    <li className={cls('tl', 'tl--trace', `tl--${s.status}`, `tl--k-${s.kind}`)}>
      <span className="tl__icon">{kindIcon(s.kind)}</span>
      <div className="tl__body">
        <div className="tl__row">
          <span className="tl__step">#{s.step}</span>
          <span className="tl__title">{s.title}</span>
          <span className="tl__kind">{STEP_KIND_LABEL[s.kind] ?? s.kind}</span>
          <code className="tl__name">{s.name}</code>
          <span className="tl__spacer" />
          <span className={cls('tl__status', `st--${s.status}`)}>
            <StatusDot status={s.status} />
            {STEP_STATUS_LABEL[s.status] ?? s.status}
          </span>
          <span className="tl__dur">{fmtMs(s.duration_ms)}</span>
        </div>
        {s.output_summary && <div className="tl__out">{s.output_summary}</div>}
        <div className="tl__meta">
          {s.model && <Chip tone="violet">{s.model}</Chip>}
          {s.tokens && (s.tokens.prompt > 0 || s.tokens.completion > 0) && (
            <span className="muted small">
              токены: {fmtNum(s.tokens.prompt)} → {fmtNum(s.tokens.completion)}
            </span>
          )}
          {s.source_ids?.length > 0 && (
            <span className="small">
              источники: <Markers ids={s.source_ids} />
            </span>
          )}
          {hasInput && (
            <button className={cls('link-btn', open && 'is-open')} onClick={() => setOpen((v) => !v)}>
              вход <IconChevron size={12} />
            </button>
          )}
        </div>
        {s.notes?.length > 0 && (
          <ul className="tl__notes">
            {s.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        )}
        {open && <pre className="json">{JSON.stringify(s.input, null, 2)}</pre>}
      </div>
    </li>
  );
}

export function TraceView({ trace }: { trace: Trace }) {
  const sm = trace.summary;
  return (
    <div className="trace">
      <div className="kpis kpis--5">
        <div className="kpi">
          <div className="kpi__label">Режим</div>
          <div className="kpi__value">{sm.mode === 'llm' ? 'LLM-агент' : 'Правила'}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Вызовы инструментов</div>
          <div className="kpi__value">{fmtNum(sm.tool_calls)}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Вызовы LLM</div>
          <div className="kpi__value">{fmtNum(sm.llm_calls)}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Токены (вход → выход)</div>
          <div className="kpi__value">
            {fmtNum(sm.tokens?.prompt)} → {fmtNum(sm.tokens?.completion)}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Длительность</div>
          <div className="kpi__value">{fmtMs(sm.duration_ms)}</div>
        </div>
      </div>
      {sm.plan?.length > 0 && (
        <div className="card card--pad">
          <div className="muted small strong">План агента</div>
          <div className="plan">
            {sm.plan.map((p, i) => (
              <span key={i} className="plan__item">
                <code>{p}</code>
                {i < sm.plan.length - 1 && <span className="plan__arrow">→</span>}
              </span>
            ))}
          </div>
          {sm.adaptations?.length > 0 && (
            <>
              <div className="muted small strong" style={{ marginTop: 12 }}>
                Адаптации по ходу выполнения
              </div>
              <ul className="adapt">
                {sm.adaptations.map((a, i) => (
                  <li key={i}>
                    <IconRepair size={14} /> {a}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      <div className="card card--pad">
        <div className="muted small strong">
          Шаги ({trace.steps.length}) · trace_id <code>{trace.trace_id}</code>
        </div>
        <ol className="timeline timeline--trace">
          {trace.steps.map((s, i) => (
            <TraceStepCard key={`${s.step}-${i}`} s={s} />
          ))}
        </ol>
      </div>
    </div>
  );
}
