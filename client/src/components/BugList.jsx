import { Badge, Button, EmptyState, Spinner } from './ui.jsx'
import { STATUS_LABELS, STATUS_STYLES } from '../lib/labels.js'

export default function BugList({
  bugs,
  loading,
  selectedId,
  runningIds,
  onSelect,
  onAddClick,
  onRunPending,
  onRerunAll,
}) {
  const reviewedCount = bugs.filter((b) => b.status === 'reviewed').length
  const pendingCount = bugs.filter((b) => !b.llm_output_json).length
  const pendingRunning = bugs.some(
    (b) => !b.llm_output_json && runningIds.has(b.id),
  )

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-term-line bg-term-panel">
      <div className="flex items-center justify-between gap-2 border-b border-term-line px-3 py-2">
        <div className="min-w-0">
          <h2 className="text-[14px] text-term-fg">bug-reports</h2>
          <p className="text-[13px] text-term-dim">
            {bugs.length} total · {reviewedCount} reviewed
          </p>
        </div>
        <Button variant="primary" onClick={onAddClick}>
          + add
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-term-line px-3 py-1.5">
        <Button
          variant="primary"
          disabled={pendingCount === 0}
          loading={pendingRunning}
          onClick={onRunPending}
        >
          run pending
          {pendingCount > 0 ? ` · ${pendingCount}` : ''}
        </Button>
        <Button disabled={bugs.length === 0} onClick={onRerunAll}>
          re-run all
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && bugs.length === 0 && (
          <p className="flex items-center gap-2 px-3 py-3 text-[14px] text-term-dim">
            <Spinner />
            loading…
          </p>
        )}

        {!loading && bugs.length === 0 && (
          <div className="px-3 py-2">
            <EmptyState
              title="no bug reports yet"
              description="run supabase/seed.sql, or add one manually"
            />
          </div>
        )}

        <ul>
          {bugs.map((bug) => {
            const selected = bug.id === selectedId
            const running = runningIds.has(bug.id)
            return (
              <li key={bug.id}>
                <button
                  onClick={() => onSelect(bug.id)}
                  aria-current={selected ? 'true' : undefined}
                  className={`flex w-full gap-1.5 border-l-2 py-1.5 pr-3 text-left transition-colors duration-75
                    ${
                      selected
                        ? 'border-ansi-cyan bg-term-sel/40'
                        : 'border-transparent hover:bg-term-raise'
                    }`}
                >
                  <span
                    className={`flex w-3 shrink-0 items-start justify-center pl-1 text-[14px] ${
                      running
                        ? 'text-ansi-yellow'
                        : selected
                          ? 'text-ansi-cyan'
                          : 'text-term-faint'
                    }`}
                    aria-hidden="true"
                  >
                    {running ? <Spinner /> : selected ? '▸' : ' '}
                  </span>

                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 block text-[14px] leading-snug text-term-fg">
                      {bug.report_text}
                    </span>
                    <span className="mt-0.5 flex items-center gap-1.5 text-[13px]">
                      <Badge
                        className={
                          running
                            ? 'text-ansi-yellow'
                            : STATUS_STYLES[bug.status]
                        }
                      >
                        {running
                          ? 'running'
                          : (STATUS_LABELS[bug.status] ?? bug.status)}
                      </Badge>
                      {bug.source === 'manual' && (
                        <Badge className="text-term-faint">manual</Badge>
                      )}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </aside>
  )
}
