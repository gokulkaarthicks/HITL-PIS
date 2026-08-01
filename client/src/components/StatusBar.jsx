import { formatPercent } from '../lib/labels.js'

/** Bottom status line, in the spirit of the iTerm2 / tmux status bar. */
export default function StatusBar({
  reviewerId,
  activePrompt,
  bugs,
  evaluation,
  llmRunning = 0,
  llmQueued = 0,
  llmConcurrency = 5,
}) {
  const reviewed = bugs.filter((b) => b.status === 'reviewed').length
  const llmBusy = llmRunning > 0 || llmQueued > 0
  const liveAccuracy =
    evaluation?.candidate_decision === 'rejected'
      ? evaluation.previous.overall_accuracy
      : evaluation?.active.overall_accuracy

  return (
    <footer className="flex shrink-0 items-center gap-3 overflow-x-auto border-t border-term-line bg-term-panel px-3 py-1 text-[13px] whitespace-nowrap">
      <span className="text-ansi-green">{reviewerId}</span>
      <span className="text-term-faint">│</span>

      <span className="text-term-dim">
        prompt{' '}
        <span className="text-ansi-cyan">
          {activePrompt?.version_name ?? '--'}
        </span>
      </span>
      <span className="text-term-faint">│</span>

      <span className="text-term-dim">
        reviewed{' '}
        <span className="text-term-fg">
          {reviewed}/{bugs.length}
        </span>
      </span>
      <span className="text-term-faint">│</span>

      <span className="text-term-dim">
        llm{' '}
        <span className={llmBusy ? 'text-ansi-yellow' : 'text-term-fg'}>
          {llmRunning}/{llmConcurrency}
          {llmQueued > 0 ? ` · ${llmQueued} queued` : ''}
        </span>
      </span>
      <span className="text-term-faint">│</span>

      <span className="text-term-dim">
        accuracy{' '}
        <span className="text-term-fg">
          {liveAccuracy == null ? '--' : formatPercent(liveAccuracy)}
        </span>
      </span>

      <span className="flex-1" />

      <span className="text-term-faint">
        {evaluation?.regression_count > 0
          ? `${evaluation.regression_count} regression${
              evaluation.regression_count === 1 ? '' : 's'
            }`
          : 'no regressions'}
      </span>
    </footer>
  )
}
