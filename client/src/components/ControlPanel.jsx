import { useEffect, useState } from 'react'
import MetricsPanel from './MetricsPanel.jsx'
import { Button, EmptyState, Rule } from './ui.jsx'
import { formatTimestamp } from '../lib/labels.js'

/** Live elapsed seconds while a run is in flight. */
function useElapsedSeconds(running) {
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    if (!running) return undefined
    setSeconds(0)
    const startedAt = Date.now()
    const timer = setInterval(
      () => setSeconds(Math.floor((Date.now() - startedAt) / 1000)),
      1000,
    )
    return () => clearInterval(timer)
  }, [running])

  return seconds
}

export default function ControlPanel({
  activePrompt,
  promptCount,
  evaluation,
  improving,
  evaluating,
  evalProgress,
  onImprove,
  onRunEvaluation,
}) {
  const [showPrompt, setShowPrompt] = useState(false)
  const elapsed = useElapsedSeconds(evaluating)

  const corrections = activePrompt?.available_corrections_count ?? 0
  const hasImprovedPrompt = promptCount > 1

  return (
    <aside className="flex h-full w-80 shrink-0 flex-col gap-5 overflow-y-auto border-l border-term-line bg-term-panel p-3">
      <section className="space-y-2">
        <Rule>active prompt</Rule>

        {!activePrompt ? (
          <EmptyState
            title="no active prompt"
            description="run supabase/seed.sql to create the baseline"
          />
        ) : (
          <div className="space-y-1 text-[13px]">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-ansi-cyan">{activePrompt.version_name}</span>
              <span className="text-[12px] text-term-faint">
                {formatTimestamp(activePrompt.created_at)}
              </span>
            </div>
            <p className="text-[12px] text-term-dim">
              built from {activePrompt.created_from_corrections_count} correction
              {activePrompt.created_from_corrections_count === 1 ? '' : 's'} ·{' '}
              {promptCount} version{promptCount === 1 ? '' : 's'} total
            </p>

            <button
              onClick={() => setShowPrompt((v) => !v)}
              className="text-[12px] text-term-dim underline-offset-2 hover:text-ansi-cyan hover:underline"
            >
              {showPrompt ? '▾ hide prompt text' : '▸ view prompt text'}
            </button>

            {showPrompt && (
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap border border-term-line bg-term-bg p-2 text-[12px] leading-relaxed text-term-dim">
                {activePrompt.prompt_text}
              </pre>
            )}

            {!hasImprovedPrompt && (
              <EmptyState title="no improved prompt yet - baseline is still active" />
            )}
          </div>
        )}
      </section>

      <section className="space-y-2">
        <Rule>improve</Rule>
        <Button
          variant="primary"
          className="w-full"
          loading={improving}
          disabled={corrections === 0}
          onClick={onImprove}
        >
          improve prompt
        </Button>
        <p className="text-[12px] leading-relaxed text-term-faint">
          <span># </span>
          {corrections === 0
            ? 'save at least one correction to enable this'
            : `builds a new version from ${corrections} saved correction${
                corrections === 1 ? '' : 's'
              }`}
        </p>
      </section>

      <section className="space-y-2">
        <Rule>evaluation</Rule>
        <Button className="w-full" loading={evaluating} onClick={onRunEvaluation}>
          run evaluation
        </Button>
        {evaluating && (
          <div className="space-y-1">
            <div className="flex items-baseline justify-between gap-2 text-[12px]">
              <span className="text-term-dim">
                {evalProgress
                  ? `scoring ${evalProgress.completed} / ${evalProgress.total}`
                  : 'starting…'}
              </span>
              <span className="tabular-nums text-term-faint">{elapsed}s</span>
            </div>
            {evalProgress && (
              <div
                className="h-1 w-full bg-term-raise"
                role="progressbar"
                aria-valuenow={evalProgress.completed}
                aria-valuemin={0}
                aria-valuemax={evalProgress.total}
              >
                <div
                  className="h-full bg-ansi-cyan transition-[width] duration-200"
                  style={{
                    width: `${
                      (evalProgress.completed / evalProgress.total) * 100
                    }%`,
                  }}
                />
              </div>
            )}
          </div>
        )}
        <MetricsPanel evaluation={evaluation} />
      </section>
    </aside>
  )
}
