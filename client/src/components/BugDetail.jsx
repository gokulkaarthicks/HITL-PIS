import TriageForm from './TriageForm.jsx'
import { Badge, Button, EmptyState, Rule } from './ui.jsx'
import { STATUS_LABELS, STATUS_STYLES, formatTimestamp } from '../lib/labels.js'

function MetaRow({ label, value }) {
  return (
    <div className="flex gap-2">
      <dt className="w-20 shrink-0 text-term-faint">{label}</dt>
      <dd className="text-term-dim">{value}</dd>
    </div>
  )
}

export default function BugDetail({
  bug,
  running,
  saving,
  onRun,
  onSave,
  promptVersionName,
}) {
  if (!bug) {
    return (
      <main className="flex-1 overflow-y-auto p-4">
        <EmptyState
          title="no bug report selected"
          description="pick one from the list on the left, or add a new one"
        />
      </main>
    )
  }

  return (
    <main className="flex-1 overflow-y-auto p-4">
      <div className="mx-auto max-w-3xl space-y-5">
        <section className="space-y-2">
          <div className="flex items-center gap-2 text-[12px]">
            <Badge className={STATUS_STYLES[bug.status]}>
              {STATUS_LABELS[bug.status] ?? bug.status}
            </Badge>
            {bug.reviewer_id && (
              <span className="text-term-faint">
                last touched by {bug.reviewer_id}
              </span>
            )}
          </div>

          <p className="whitespace-pre-wrap border-l-2 border-term-line py-0.5 pl-3 text-[14px] leading-relaxed text-term-fg">
            {bug.report_text}
          </p>

          <dl className="space-y-0.5 text-[12px]">
            <MetaRow label="created" value={formatTimestamp(bug.created_at)} />
            <MetaRow label="llm run" value={formatTimestamp(bug.llm_run_at)} />
            <MetaRow label="reviewed" value={formatTimestamp(bug.reviewed_at)} />
          </dl>
        </section>

        <section className="space-y-3">
          <Rule>triage output</Rule>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[12px] text-term-dim">
              active prompt{' '}
              <span className="text-ansi-cyan">{promptVersionName ?? '--'}</span>
            </p>
            <Button variant="primary" loading={running} onClick={() => onRun(bug.id)}>
              {bug.llm_output_json ? 're-run llm' : 'run llm'}
            </Button>
          </div>

          {!bug.llm_output_json ? (
            <EmptyState
              title="no llm run yet"
              description="run the llm to generate a structured triage you can correct"
            />
          ) : (
            <TriageForm bug={bug} saving={saving} onSave={onSave} />
          )}

          {bug.llm_output_json && !bug.human_corrected_json && (
            <EmptyState title="no correction saved yet - edit the fields above and save" />
          )}
        </section>

        {bug.llm_output_json?.rationale && (
          <section className="space-y-2">
            <Rule>model reason</Rule>
            <p className="text-[13px] leading-relaxed text-term-dim">
              {bug.llm_output_json.rationale}
            </p>
          </section>
        )}
      </div>
    </main>
  )
}
