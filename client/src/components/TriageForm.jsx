import { useEffect, useMemo, useState } from 'react'
import { Button, Field, Select, TextArea } from './ui.jsx'
import { COMPONENTS, SEVERITIES, SEVERITY_STYLES } from '../lib/labels.js'

const EMPTY = { severity: 'medium', component: 'unknown', rationale: '' }

/**
 * Editable view of the triage output.
 *
 * Seeded from the saved human correction when one exists, otherwise from the
 * raw LLM output, so a reviewer always edits the most recent version of truth.
 */
export default function TriageForm({ bug, saving, onSave }) {
  const initial = useMemo(
    () => bug.human_corrected_json ?? bug.llm_output_json ?? EMPTY,
    [bug.human_corrected_json, bug.llm_output_json],
  )

  const [draft, setDraft] = useState(initial)

  // Re-seed when a different bug is selected or a new LLM run lands.
  useEffect(() => setDraft(initial), [initial, bug.id])

  const llm = bug.llm_output_json
  const dirty =
    draft.severity !== initial.severity ||
    draft.component !== initial.component ||
    (draft.rationale ?? '') !== (initial.rationale ?? '')

  const changedFromLlm = llm
    ? {
        severity: draft.severity !== llm.severity,
        component: draft.component !== llm.component,
      }
    : { severity: false, component: false }

  const update = (patch) => setDraft((current) => ({ ...current, ...patch }))

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        onSave(draft)
      }}
      className="@container space-y-3"
    >
      {/*
        Container query, not a viewport breakpoint: this form sits between two
        fixed-width sidebars, so window width says nothing useful about how much
        room the fields actually have.
      */}
      <div className="grid grid-cols-1 gap-3 @lg:grid-cols-2">
        <Field
          label="severity"
          hint={changedFromLlm.severity ? 'modified' : undefined}
        >
          <Select
            value={draft.severity}
            options={SEVERITIES}
            onChange={(e) => update({ severity: e.target.value })}
          />
        </Field>

        <Field
          label="component"
          hint={changedFromLlm.component ? 'modified' : undefined}
        >
          <Select
            value={draft.component}
            options={COMPONENTS}
            onChange={(e) => update({ component: e.target.value })}
          />
        </Field>
      </div>

      <Field label="reason" hint="not scored">
        <TextArea
          rows={3}
          value={draft.rationale ?? ''}
          placeholder="why this severity and component?"
          onChange={(e) => update({ rationale: e.target.value })}
        />
      </Field>

      {llm && (
        <p className="flex flex-wrap items-center gap-2 text-[12px] text-term-dim">
          <span className="text-term-faint">llm output</span>
          <span className={SEVERITY_STYLES[llm.severity]}>{llm.severity}</span>
          <span className="text-term-faint">/</span>
          <span className="text-term-fg">{llm.component}</span>
        </p>
      )}

      <div className="flex items-center gap-3 pt-0.5">
        <Button
          type="submit"
          variant="primary"
          loading={saving}
          disabled={!dirty && !!bug.human_corrected_json}
        >
          {bug.human_corrected_json ? 'update correction' : 'save correction'}
        </Button>
        {dirty && (
          <span className="text-[12px] text-ansi-yellow">unsaved changes</span>
        )}
        {!dirty && bug.human_corrected_json && (
          <span className="text-[12px] text-ansi-green">correction saved</span>
        )}
      </div>
    </form>
  )
}
