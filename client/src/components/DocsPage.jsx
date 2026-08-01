const SECTIONS = [
  {
    title: 'approach',
    points: [
      'Capture every triage, correction, and prompt version; rebuild each candidate from the baseline plus correction-derived calibration and a few distinct examples.',
      'Score on an 18-example held-out set (separate from the 93-report review pool) with deterministic exact match, no LLM judge.',
      'Activate a candidate only when overall accuracy rises and regression count is zero, so local gains cannot quietly break working cases.',
    ],
  },
  {
    title: 'tradeoffs',
    points: [
      'Few-shot from corrections is fast, readable, and reversible, but context grows and gains plateau.',
      'Exact-match scoring is auditable, but gives no partial credit and treats severity as categorical.',
      'Compare each candidate to the live prompt (not v1) so the gate answers “is this deploy safe?” rather than “how far have we come?”',
      'No login keeps the demo frictionless, but reviewer identity is only a local label and concurrent edits are unsafe.',
    ],
  },
  {
    title: 'assumptions & limitations',
    points: [
      'Saved corrections are trusted ground truth; one bad correction can shape every later candidate because there is no agreement workflow.',
      'Labels are treated as stable and defensible, even though reviewers can disagree on borderline cases.',
      'Eighteen examples are too few for confidence intervals; rationale is stored for humans but not scored.',
      'Both evaluation arms use the same model and decoding settings so the prompt text is the only variable.',
    ],
  },
  {
    title: 'with more time',
    points: [
      'Grow a versioned gold set with multiple reviewers, report agreement and confidence intervals, and gate on statistical improvement plus zero regressions.',
      'Add authentication, roles, optimistic locking, candidate approval, and one-click rollback.',
      'Show per-example diffs and a full history from v1 through every accepted or rejected candidate, with cost and latency per run.',
      'Queue long evaluations, retry provider rate limits without counting them as model errors, and retrieve relevant corrections before considering fine-tuning.',
    ],
  },
]

function SectionHeading({ children }) {
  return (
    <h2 className="mb-4 text-1xl font-semibold tracking-tight text-ansi-green">
      {children}
    </h2>
  )
}

function PointList({ points }) {
  return (
    <ul className="list-disc space-y-3 pl-5 text-justify text-[15px] leading-7 text-[#d1d5db]">
      {points.map((point) => (
        <li key={point}>{point}</li>
      ))}
    </ul>
  )
}

export default function DocsPage() {
  return (
    <div className="flex min-h-full flex-col bg-term-bg font-sans antialiased">
      <header className="mx-auto flex w-full max-w-3xl shrink-0 items-center gap-3 px-5 py-6 sm:px-8">
        <p className="text-sm text-term-dim">
          hitl-prompt-improvement / docs
        </p>
        <span className="flex-1" />
        <a
          href="/"
          className="shrink-0 text-sm font-medium text-ansi-orange hover:text-ansi-orange/80 focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-ansi-orange"
        >
          ← application
        </a>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 space-y-12 px-5 pb-16 sm:px-8">
        <header className="space-y-3">
          <h1 className="text-3xl font-semibold tracking-tight text-ansi-green">
            Design
          </h1>
          <p className="text-justify text-[15px] leading-7 text-[#d1d5db]">
            How the review → improve → measure loop works, what was traded away,
            and what would change with more time.
          </p>
        </header>

        <section>
          <SectionHeading>loop</SectionHeading>
          <p className="text-justify text-[15px] leading-7 text-[#d1d5db]">
            bug report → LLM triage → human correction → candidate prompt →
            held-out evaluation → activate or reject
          </p>
        </section>

        {SECTIONS.map((section) => (
          <section key={section.title}>
            <SectionHeading>{section.title}</SectionHeading>
            <PointList points={section.points} />
          </section>
        ))}
      </main>
    </div>
  )
}
