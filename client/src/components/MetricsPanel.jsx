import { EmptyState } from './ui.jsx'
import { formatDelta, formatPercent, formatTimestamp } from '../lib/labels.js'

/** Aligned key/value line, the way `watch` or a status command prints one. */
function Row({ label, value, valueClass = 'text-term-fg' }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="shrink-0 text-term-dim">{label}</span>
      <span className="h-px min-w-2 flex-1 self-center bg-term-line/60" />
      <span className={`shrink-0 tabular-nums ${valueClass}`}>{value}</span>
    </div>
  )
}

export default function MetricsPanel({ evaluation }) {
  if (!evaluation) {
    return (
      <EmptyState
        title="no previous evaluation"
        description="run one to score the baseline and active prompts"
      />
    )
  }

  const {
    previous,
    active,
    overall_delta: delta,
    regression_count: regressions,
    protected_regression_count: protectedRegressions = 0,
    remaining_error_reduction: errorReduction = 0,
    ordinary_regression_limit: ordinaryRegressionLimit = 2,
    previous_is_cached: previousIsCached,
  } = evaluation
  const unchanged = previous.prompt_version_id === active.prompt_version_id
  const decision = evaluation.candidate_decision
  const regressionDetails = evaluation.regression_details ?? []
  const ordinaryRegressions = regressions - protectedRegressions

  const deltaClass =
    delta > 0 ? 'text-ansi-green' : delta < 0 ? 'text-ansi-red' : 'text-term-dim'
  const regressionClass =
    regressions > 0 ? 'text-ansi-yellow' : 'text-ansi-green'

  return (
    <div className="space-y-1 text-[14px]">
      <Row
        label={`previous  ${previous.version_name}`}
        value={formatPercent(previous.overall_accuracy)}
      />
      <Row
        label={`${decision ? 'candidate' : 'current  '} ${active.version_name}`}
        value={formatPercent(active.overall_accuracy)}
        valueClass="text-ansi-cyan tabular-nums"
      />
      <Row label="delta" value={formatDelta(delta)} valueClass={deltaClass} />
      <Row
        label="regressions"
        value={regressions}
        valueClass={regressionClass}
      />
      {!unchanged && (
        <Row
          label="error reduction (≥30%)"
          value={formatPercent(errorReduction)}
          valueClass={errorReduction >= 0.3 ? 'text-ansi-green' : 'text-ansi-red'}
        />
      )}
      {decision && (
        <>
          <Row
            label="ordinary regression budget"
            value={`${ordinaryRegressions} / ${ordinaryRegressionLimit}`}
            valueClass={
              ordinaryRegressions <= ordinaryRegressionLimit
                ? 'text-ansi-green'
                : 'text-ansi-red'
            }
          />
          <Row
            label="protected regressions"
            value={protectedRegressions}
            valueClass={protectedRegressions === 0 ? 'text-ansi-green' : 'text-ansi-red'}
          />
        </>
      )}
      {decision && (
        <Row
          label="decision"
          value={decision}
          valueClass={decision === 'promoted' ? 'text-ansi-green' : 'text-ansi-red'}
        />
      )}

      {regressionDetails.length > 0 && (
        <details open className="mt-2 border border-term-line bg-term-bg p-2 text-[12px] leading-relaxed">
          <summary className="cursor-pointer text-term-dim">
            regression details ({regressionDetails.length})
          </summary>
          <div className="mt-2 space-y-3">
            {regressionDetails.map((detail, index) => (
              <div key={detail.example_id} className="space-y-1">
                <p
                  className={detail.protected ? 'text-ansi-red' : 'text-ansi-yellow'}
                >
                  {index + 1}. {detail.protected ? 'protected' : 'ordinary'} regression
                </p>
                <p className="text-term-fg">{detail.report_text}</p>
                <p className="text-term-dim">
                  expected {detail.expected?.severity ?? '--'} /{' '}
                  {detail.expected?.component ?? '--'} · control{' '}
                  {detail.control_prediction?.severity ?? '--'} /{' '}
                  {detail.control_prediction?.component ?? '--'} · candidate{' '}
                  {detail.candidate_prediction?.severity ?? '--'} /{' '}
                  {detail.candidate_prediction?.component ?? '--'}
                </p>
              </div>
            ))}
          </div>
        </details>
      )}

      <div className="pt-2" />

      <Row
        label="severity"
        value={`${formatPercent(previous.severity_accuracy)} → ${formatPercent(
          active.severity_accuracy,
        )}`}
        valueClass={
          decision
            ? evaluation.severity_delta >= 0
              ? 'text-ansi-green tabular-nums'
              : 'text-ansi-red tabular-nums'
            : 'text-term-dim tabular-nums'
        }
      />
      <Row
        label="component"
        value={`${formatPercent(previous.component_accuracy)} → ${formatPercent(
          active.component_accuracy,
        )}`}
        valueClass={
          decision
            ? evaluation.component_delta >= 0
              ? 'text-ansi-green tabular-nums'
              : 'text-ansi-red tabular-nums'
            : 'text-term-dim tabular-nums'
        }
      />
      <Row
        label="newly fixed"
        value={`${evaluation.improved_count} of ${evaluation.example_count}`}
        valueClass="text-term-dim tabular-nums"
      />
      {/*
        Always show when the previous arm was measured, not only right after a
        cached run. GET /eval/latest reconstructs from stored rows and cannot
        know whether the arm was reused, so relying on the cached flag alone
        would make this information vanish on reload.
      */}
      {!unchanged && (
        <Row
          label="previous measured"
          value={formatTimestamp(previous.created_at)}
          valueClass="text-term-dim"
        />
      )}
      <Row
        label="last run"
        value={formatTimestamp(evaluation.evaluated_at)}
        valueClass="text-term-dim"
      />

      {unchanged && (
        <p className="pt-2 text-[13px] leading-relaxed text-term-faint">
          <span># </span>
          only one prompt version exists, so both rows show the same score.
          improve the prompt, then re-run to get a real comparison.
        </p>
      )}

      {/* A reused score must never read as freshly measured. */}
      {previousIsCached && !unchanged && (
        <p className="pt-2 text-[13px] leading-relaxed text-term-faint">
          <span># </span>
          previous row reused from its run at{' '}
          {formatTimestamp(previous.created_at)} - not re-scored
        </p>
      )}
    </div>
  )
}
