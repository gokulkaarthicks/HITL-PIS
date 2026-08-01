import { useEffect, useRef, useState } from 'react'
import { Button, Field, Input } from './ui.jsx'

export default function ResetDemoDialog({ open, submitting, onClose, onSubmit }) {
  const [confirmation, setConfirmation] = useState('')
  const confirmationRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setConfirmation('')
    requestAnimationFrame(() => confirmationRef.current?.focus())
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape' && !submitting) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose, open, submitting])

  if (!open) return null

  const confirmed = confirmation === 'RESET'

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4"
      onClick={() => !submitting && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Reset demo"
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-lg border border-ansi-red/50 bg-term-panel shadow-2xl"
      >
        <div className="flex items-center gap-2 border-b border-term-line px-3 py-1.5">
          <span className="text-[14px] text-ansi-red">reset-demo</span>
          <span className="flex-1" />
          <button
            onClick={onClose}
            disabled={submitting}
            aria-label="Close"
            className="text-term-faint hover:text-term-fg disabled:opacity-40"
          >
            ✕
          </button>
        </div>

        <form
          className="space-y-3 p-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (confirmed) onSubmit()
          }}
        >
          <p className="text-[13px] leading-relaxed text-term-dim">
            Restores the 93 seeded reports to <span className="text-term-fg">not run</span>,
            deletes manual reports, corrections, improved prompts, and evaluation
            history, then reactivates <span className="text-ansi-cyan">v1-baseline</span>.
          </p>

          <Field label="type RESET to confirm">
            <Input
              ref={confirmationRef}
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </Field>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" disabled={submitting} onClick={onClose}>
              cancel
            </Button>
            <Button
              type="submit"
              variant="danger"
              loading={submitting}
              disabled={!confirmed}
            >
              reset everything
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
