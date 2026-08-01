import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AddBugDialog from './components/AddBugDialog.jsx'
import BugDetail from './components/BugDetail.jsx'
import BugList from './components/BugList.jsx'
import ControlPanel from './components/ControlPanel.jsx'
import ResetDemoDialog from './components/ResetDemoDialog.jsx'
import StatusBar from './components/StatusBar.jsx'
import { Spinner, Toast } from './components/ui.jsx'
import { api } from './lib/api.js'
import { getReviewerId } from './lib/reviewer.js'

/** Max concurrent POST /bugs/{id}/run calls from the UI. */
const LLM_RUN_CONCURRENCY = 5

export default function App() {
  const reviewerId = useMemo(() => getReviewerId(), [])

  const [bugs, setBugs] = useState([])
  const [prompts, setPrompts] = useState([])
  const [activePrompt, setActivePrompt] = useState(null)
  const [evaluation, setEvaluation] = useState(null)
  const [selectedId, setSelectedId] = useState(null)

  const [loadingBugs, setLoadingBugs] = useState(true)
  /** Bug ids queued or actively running an LLM classify. */
  const [runningIds, setRunningIds] = useState(() => new Set())
  /** How many /run requests are in flight right now (≤ LLM_RUN_CONCURRENCY). */
  const [llmActiveCount, setLlmActiveCount] = useState(0)
  const runQueueRef = useRef([])
  const activeRunCountRef = useRef(0)
  const scheduledIdsRef = useRef(new Set())
  const runDepsRef = useRef({ reviewerId, replaceBug: null, notify: null })
  const [saving, setSaving] = useState(false)
  const [improving, setImproving] = useState(false)
  const [evaluating, setEvaluating] = useState(false)
  const [evalProgress, setEvalProgress] = useState(null)
  const [addOpen, setAddOpen] = useState(false)
  const [addSubmitting, setAddSubmitting] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetting, setResetting] = useState(false)

  const [toast, setToast] = useState(null)
  const notify = useCallback((message, kind = 'error') => {
    setToast({ message, kind })
  }, [])

  // Auto-dismiss success toasts; leave errors up until dismissed.
  useEffect(() => {
    if (!toast || toast.kind === 'error') return undefined
    const timer = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(timer)
  }, [toast])

  const refreshPrompts = useCallback(async () => {
    const [active, all] = await Promise.all([api.activePrompt(), api.listPrompts()])
    setActivePrompt(active)
    setPrompts(all)
  }, [])

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const list = await api.listBugs()
        if (cancelled) return
        setBugs(list)
        setSelectedId((current) => current ?? list[0]?.id ?? null)
      } catch (error) {
        if (!cancelled) notify(error.message)
      } finally {
        if (!cancelled) setLoadingBugs(false)
      }

      // Prompt and evaluation state load independently: a failure in either
      // should not blank out the bug list.
      try {
        if (!cancelled) await refreshPrompts()
      } catch (error) {
        if (!cancelled) notify(error.message)
      }
      try {
        const latest = await api.latestEvaluation()
        if (!cancelled) setEvaluation(latest)
      } catch (error) {
        if (!cancelled) notify(error.message)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [notify, refreshPrompts])

  const selectedBug = bugs.find((bug) => bug.id === selectedId) ?? null

  const replaceBug = useCallback((updated) => {
    setBugs((current) =>
      current.map((bug) => (bug.id === updated.id ? updated : bug)),
    )
  }, [])

  runDepsRef.current = { reviewerId, replaceBug, notify }

  const pumpLlmRuns = useCallback(() => {
    while (
      activeRunCountRef.current < LLM_RUN_CONCURRENCY &&
      runQueueRef.current.length > 0
    ) {
      const bugId = runQueueRef.current.shift()
      activeRunCountRef.current += 1
      setLlmActiveCount(activeRunCountRef.current)

      void (async () => {
        const deps = runDepsRef.current
        try {
          deps.replaceBug(await api.runLlm(bugId, deps.reviewerId))
        } catch (error) {
          deps.notify(error.message)
        } finally {
          activeRunCountRef.current -= 1
          setLlmActiveCount(activeRunCountRef.current)
          scheduledIdsRef.current.delete(bugId)
          setRunningIds(new Set(scheduledIdsRef.current))
          pumpLlmRuns()
        }
      })()
    }
  }, [])

  const enqueueLlmRuns = useCallback(
    (bugIds) => {
      let added = false
      for (const bugId of bugIds) {
        if (scheduledIdsRef.current.has(bugId)) continue
        scheduledIdsRef.current.add(bugId)
        runQueueRef.current.push(bugId)
        added = true
      }
      if (!added) return
      setRunningIds(new Set(scheduledIdsRef.current))
      pumpLlmRuns()
    },
    [pumpLlmRuns],
  )

  const handleRun = useCallback(
    (bugId) => {
      enqueueLlmRuns([bugId])
    },
    [enqueueLlmRuns],
  )

  const handleRunPending = useCallback(() => {
    const pendingIds = bugs
      .filter((bug) => !bug.llm_output_json)
      .map((bug) => bug.id)
    if (pendingIds.length === 0) {
      notify('No pending bugs to run.', 'success')
      return
    }
    enqueueLlmRuns(pendingIds)
  }, [bugs, enqueueLlmRuns, notify])

  const handleRerunAll = useCallback(() => {
    const ids = bugs.map((bug) => bug.id)
    if (ids.length === 0) return
    enqueueLlmRuns(ids)
  }, [bugs, enqueueLlmRuns])

  const handleSaveCorrection = useCallback(
    async (draft) => {
      if (!selectedBug) return
      setSaving(true)
      try {
        replaceBug(await api.saveCorrection(selectedBug.id, draft, reviewerId))
        await refreshPrompts() // correction count drives the Improve button
        notify('Correction saved.', 'success')
      } catch (error) {
        notify(error.message)
      } finally {
        setSaving(false)
      }
    },
    [notify, refreshPrompts, replaceBug, reviewerId, selectedBug],
  )

  const handleAddBug = useCallback(
    async (text) => {
      setAddSubmitting(true)
      try {
        const created = await api.createBug(text)
        setBugs((current) => [created, ...current])
        setSelectedId(created.id)
        setAddOpen(false)
        notify('Bug report added.', 'success')
      } catch (error) {
        notify(error.message)
      } finally {
        setAddSubmitting(false)
      }
    },
    [notify],
  )

  const handleImprove = useCallback(async () => {
    setImproving(true)
    try {
      const created = await api.improvePrompt()
      await refreshPrompts()
      notify(
        `Created ${created.version_name} from ${created.created_from_corrections_count} corrections. Run an evaluation to compare it.`,
        'success',
      )
    } catch (error) {
      notify(error.message)
    } finally {
      setImproving(false)
    }
  }, [notify, refreshPrompts])

  const handleRunEvaluation = useCallback(async () => {
    setEvaluating(true)
    setEvalProgress(null)
    try {
      const result = await api.runEvaluationStream((event) =>
        setEvalProgress({ completed: event.completed, total: event.total }),
      )
      setEvaluation(result)
      notify('Evaluation complete.', 'success')
    } catch (error) {
      notify(error.message)
    } finally {
      setEvaluating(false)
      setEvalProgress(null)
    }
  }, [notify])

  const handleResetDemo = useCallback(
    async () => {
      setResetting(true)
      try {
        const result = await api.resetDemo()
        const list = await api.listBugs()
        setBugs(list)
        setSelectedId(list[0]?.id ?? null)
        setEvaluation(null)
        await refreshPrompts()
        setResetOpen(false)
        notify(
          `Demo reset complete: ${result.seeded_bug_count} seeded reports, v1-baseline active.`,
          'success',
        )
      } catch (error) {
        notify(error.message)
      } finally {
        setResetting(false)
      }
    },
    [notify, refreshPrompts],
  )

  const resetDisabled =
    runningIds.size > 0 || saving || improving || evaluating || addSubmitting

  return (
    <div className="flex h-full flex-col">
      {/* Prompt line: title reads as a command typed after the shell arrow. */}
      <header className="flex shrink-0 items-center gap-2 border-b border-term-line bg-term-panel px-3 py-1.5">
        <h1 className="text-[14px] text-term-dim">
          <span className="text-ansi-green" aria-hidden="true">
            ❯
          </span>{' '}
          hitl-prompt-improvement - triage · correct · improve · evaluate
        </h1>
        <span className="flex-1" />
        <a
          href="/docs"
          className="text-[14px] text-term-dim transition-colors duration-75 hover:text-ansi-cyan
            focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2
            focus-visible:outline-ansi-cyan"
        >
          docs
        </a>
        <button
          type="button"
          aria-label="Reset demo"
          title="Reset demo"
          disabled={resetDisabled || resetting}
          onClick={() => setResetOpen(true)}
          className="inline-flex h-7 w-7 items-center justify-center text-[21px] text-ansi-green
            transition-colors duration-75 hover:text-ansi-green/80
            disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-ansi-green
            focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-1
            focus-visible:outline-ansi-cyan"
        >
          {resetting ? <Spinner /> : <span aria-hidden="true">↺</span>}
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        <BugList
          bugs={bugs}
          loading={loadingBugs}
          selectedId={selectedId}
          runningIds={runningIds}
          onSelect={setSelectedId}
          onAddClick={() => setAddOpen(true)}
          onRunPending={handleRunPending}
          onRerunAll={handleRerunAll}
        />
        <BugDetail
          bug={selectedBug}
          running={selectedBug ? runningIds.has(selectedBug.id) : false}
          saving={saving}
          onRun={handleRun}
          onSave={handleSaveCorrection}
          promptVersionName={activePrompt?.version_name}
        />
        <ControlPanel
          activePrompt={activePrompt}
          promptCount={prompts.length}
          evaluation={evaluation}
          improving={improving}
          evaluating={evaluating}
          evalProgress={evalProgress}
          onImprove={handleImprove}
          onRunEvaluation={handleRunEvaluation}
        />
      </div>

      <StatusBar
        reviewerId={reviewerId}
        activePrompt={activePrompt}
        bugs={bugs}
        evaluation={evaluation}
        llmRunning={llmActiveCount}
        llmQueued={Math.max(0, runningIds.size - llmActiveCount)}
        llmConcurrency={LLM_RUN_CONCURRENCY}
      />

      <AddBugDialog
        open={addOpen}
        submitting={addSubmitting}
        onClose={() => setAddOpen(false)}
        onSubmit={handleAddBug}
      />
      <ResetDemoDialog
        open={resetOpen}
        submitting={resetting}
        onClose={() => setResetOpen(false)}
        onSubmit={handleResetDemo}
      />
      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  )
}
