const SCALE_NOTES = [
  'Add Cloudflare Queues for triage, prompt builds, and evaluations; consider Kafka later for higher throughput, replay, or multiple consumers.',
  'Keep corrections transactional and batch audit and evaluation writes; add idempotency, pooling, partitioning, and replicas as traffic grows.',
  'Use cursor pagination, filters, and matching database indexes instead of loading every report.',
  'When prompts grow, summarize repeated corrections, enforce a token budget, and keep only relevant examples.',
  'Cache results by model, prompt version, and report hash to reduce duplicate LLM calls and token cost.',
  'Use optimistic locking and show conflicts before one reviewer overwrites another reviewer\'s changes.',
]

function SectionHeading({ children }) {
  return <h2 className="mb-4 text-[14px] font-medium text-ansi-green">{children}</h2>
}

export default function DocsPage() {
  return (
    <div className="flex min-h-full flex-col bg-term-bg">
      <header className="mx-auto flex w-full max-w-4xl shrink-0 items-center gap-3 px-5 py-6 sm:px-8">
        <h1 className="text-[14px] text-term-dim">
          <span className="text-ansi-green" aria-hidden="true">
            ❯
          </span>{' '}
          hitl-prompt-improvement / docs
        </h1>
        <span className="flex-1" />
        <a
          href="/"
          className="shrink-0 text-[14px] text-ansi-green hover:text-ansi-green/80 focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-ansi-cyan"
        >
          ← application
        </a>
      </header>

      <main className="mx-auto w-full max-w-4xl flex-1 space-y-10 px-5 pb-10 sm:px-8">
        <section>
          <SectionHeading>current flow</SectionHeading>
          <p className="overflow-x-auto text-[14px] leading-7 whitespace-nowrap text-white">
            bug report → LLM triage → human correction → prompt version → held-out evaluation
          </p>
        </section>

        <section>
          <SectionHeading>if the system scales</SectionHeading>
          <ol className="space-y-6">
            {SCALE_NOTES.map((note, index) => (
              <li key={note} className="flex gap-4">
                <span className="shrink-0 text-[14px] text-white">
                  {index + 1}.
                </span>
                <p className="min-w-0 text-[14px] leading-6 text-white">
                  {note}
                </p>
              </li>
            ))}
          </ol>
        </section>
      </main>
    </div>
  )
}
