import { useEffect, useRef, useState } from 'react'
import { Button, Field, TextArea } from './ui.jsx'

const MIN_LENGTH = 10

export default function AddBugDialog({ open, submitting, onClose, onSubmit }) {
  const [text, setText] = useState('')
  const textAreaRef = useRef(null)

  useEffect(() => {
    if (open) {
      setText('')
      textAreaRef.current?.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  const trimmed = text.trim()
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_LENGTH

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Add bug report"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl border border-term-line bg-term-panel shadow-2xl"
      >
        {/* Title bar, styled like the window chrome of a terminal split. */}
        <div className="flex items-center gap-2 border-b border-term-line px-3 py-1.5">
          <span className="text-[14px] text-term-dim">add-bug-report</span>
          <span className="flex-1" />
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-term-faint hover:text-term-fg"
          >
            ✕
          </button>
        </div>

        <form
          className="space-y-3 p-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (trimmed.length >= MIN_LENGTH) onSubmit(trimmed)
          }}
        >
          <p className="text-[13px] text-term-faint">
            <span># </span>
            joins the review pool; the held-out evaluation set is unaffected
          </p>

          <Field label="report text" hint={`${trimmed.length} chars`}>
            <TextArea
              ref={textAreaRef}
              rows={6}
              value={text}
              placeholder="describe the bug as a reporter would…"
              onChange={(e) => setText(e.target.value)}
            />
          </Field>

          {tooShort && (
            <p className="text-[13px] text-ansi-yellow">
              needs at least {MIN_LENGTH} characters
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={submitting}
              disabled={trimmed.length < MIN_LENGTH}
            >
              add report
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
