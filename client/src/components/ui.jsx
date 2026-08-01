import { useEffect, useState } from 'react'

/** Shared presentational primitives, styled as terminal affordances. */

const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

/** The braille spinner every CLI tool uses, rather than a rotating SVG. */
export function Spinner({ className = '' }) {
  const [frame, setFrame] = useState(0)

  useEffect(() => {
    const timer = setInterval(
      () => setFrame((f) => (f + 1) % SPINNER_FRAMES.length),
      80,
    )
    return () => clearInterval(timer)
  }, [])

  return (
    <span className={className} aria-hidden="true">
      {SPINNER_FRAMES[frame]}
    </span>
  )
}

/** `[label]` - bracketed text, the way a TUI marks state. */
export function Badge({ children, className = 'text-term-dim' }) {
  return (
    <span className={`whitespace-nowrap ${className}`}>
      <span className="text-term-faint">[</span>
      {children}
      <span className="text-term-faint">]</span>
    </span>
  )
}

const BUTTON_VARIANTS = {
  primary:
    'text-ansi-green border-ansi-green/40 hover:bg-ansi-green hover:text-term-bg hover:border-ansi-green',
  secondary:
    'text-term-fg border-term-line hover:bg-term-fg hover:text-term-bg hover:border-term-fg',
  ghost:
    'text-term-dim border-transparent hover:text-term-fg hover:border-term-line',
  danger:
    'text-ansi-red border-ansi-red/40 hover:bg-ansi-red hover:text-term-bg hover:border-ansi-red',
}

/**
 * A command, not a call to action. Hover inverts foreground and background,
 * which is how a selected entry looks in a terminal.
 */
export function Button({
  children,
  variant = 'secondary',
  loading = false,
  className = '',
  disabled,
  ...props
}) {
  return (
    <button
      disabled={disabled || loading}
      className={`inline-flex cursor-pointer items-center justify-center gap-1.5 border px-2.5 py-1
        text-[14px] transition-colors duration-75
        disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent
        disabled:hover:text-inherit disabled:hover:border-term-line
        focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-1
        focus-visible:outline-ansi-cyan
        ${BUTTON_VARIANTS[variant]} ${className}`}
      {...props}
    >
      {loading && <Spinner />}
      {children}
    </button>
  )
}

/** Section heading: label followed by a rule, like a `man` page divider. */
export function Rule({ children, className = '' }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span className="shrink-0 text-[13px] tracking-wide text-term-dim">
        {children}
      </span>
      <span className="h-px flex-1 bg-term-line" />
    </div>
  )
}

/** Empty states read as shell comments rather than as empty cards. */
export function EmptyState({ title, description }) {
  return (
    <div className="space-y-0.5 py-1 text-[14px] leading-relaxed">
      <p className="text-term-dim">
        <span className="text-term-faint">#</span> {title}
      </p>
      {description && (
        <p className="text-term-faint">
          <span>#</span> {description}
        </p>
      )}
    </div>
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline justify-between gap-2 text-[13px] text-term-dim">
        <span className="min-w-0 truncate">{label}</span>
        {hint && <span className="shrink-0 text-ansi-yellow">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

const CONTROL =
  'w-full border border-term-line bg-term-bg px-2 py-1.5 text-[15px] text-term-fg ' +
  'focus:border-ansi-cyan focus:outline-none'

export function Select({ options, ...props }) {
  return (
    <select className={`${CONTROL} appearance-none pr-6`} {...props}>
      {options.map((option) => (
        <option key={option} value={option} className="bg-term-bg">
          {option}
        </option>
      ))}
    </select>
  )
}

export function TextArea(props) {
  return <textarea className={`${CONTROL} resize-y`} {...props} />
}

export function Input(props) {
  return <input className={CONTROL} {...props} />
}

/** Bottom-anchored line, prefixed like stderr/stdout output. */
export function Toast({ toast, onDismiss }) {
  if (!toast) return null

  const isError = toast.kind === 'error'
  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed bottom-8 right-3 z-50 flex max-w-lg items-start gap-2 border
        bg-term-panel px-3 py-2 text-[14px] shadow-lg
        ${isError ? 'border-ansi-red/40' : 'border-ansi-green/40'}`}
    >
      <span className={isError ? 'text-ansi-red' : 'text-ansi-green'}>
        {isError ? 'error:' : 'ok:'}
      </span>
      <span className="flex-1 whitespace-pre-wrap text-term-fg">
        {toast.message}
      </span>
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        className="shrink-0 cursor-pointer text-term-faint hover:text-term-fg"
      >
        ✕
      </button>
    </div>
  )
}
