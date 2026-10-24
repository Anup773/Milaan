"use client";

import Link from "next/link";
import { Fragment, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/form";
import { Loading, Notice } from "@/components/common/notice";
import { api, errorMessage } from "@/lib/api-client";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import type { AiAnswer, AiStatus } from "@/lib/ai-types";

const MAX_QUESTION = 4000;
// The API accepts 20 messages; keep one spare for the new question.
const MAX_SENT = 19;

const EXAMPLES = [
  "Give me a summary of this period's profit and loss.",
  "Which exceptions are still open, and which are high priority?",
  "What is waiting for my approval?",
  "Does the fixed-asset schedule agree with the ledger?",
  "What if Trade Receivables were 20000? Show me the impact.",
];

interface Turn {
  role: "user" | "assistant";
  text: string;
  meta?: AiAnswer;
}

/** Bold (**like this**) and nothing else, built as elements so model text can never become markup. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
  );
}

/** Paragraphs and "- " bullet lists. */
function Rich({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length > 0) {
      blocks.push(
        <ul key={`u${blocks.length}`} className="list-disc space-y-1 pl-5">
          {bullets.map((b, i) => (
            <li key={i}>{inline(b)}</li>
          ))}
        </ul>,
      );
      bullets = [];
    }
  };
  for (const line of text.split("\n")) {
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }
    flush();
    if (line.trim() !== "") blocks.push(<p key={`p${blocks.length}`}>{inline(line)}</p>);
  }
  flush();
  return <div className="space-y-2 text-sm leading-relaxed text-ink">{blocks}</div>;
}

function AnswerNotes({ meta }: { meta: AiAnswer }) {
  return (
    <div className="mt-3 space-y-2">
      {meta.unverified_figures.length > 0 ? (
        <Notice kind="warning">
          Check these before you rely on them: {meta.unverified_figures.join(", ")}. {meta.unverified_figures.length === 1 ? "It does" : "They do"} not appear in the figures I looked up, so{" "}
          {meta.unverified_figures.length === 1 ? "it may be a sum or a rounding" : "they may be sums or roundings"} I worked out myself, or a mistake.
        </Notice>
      ) : null}
      {meta.stopped === "length" ? <Notice kind="info">This answer was cut short. Ask for the rest, or ask a narrower question.</Notice> : null}
      {meta.stopped === "limit" ? <Notice kind="info">I stopped early because the question needed too many lookups.</Notice> : null}
      {meta.looked_at.length > 0 ? (
        <div className="text-xs text-ink-faint">
          <span className="mr-1.5 font-medium text-ink-soft">Looked at:</span>
          {meta.looked_at.map((l, i) => (
            <span key={i} className="mr-1.5 inline-flex items-center gap-1">
              <Link href={l.page} className={cn("underline decoration-dotted underline-offset-2", l.ok ? "text-ledger" : "text-fail")} title="Open the screen that shows this">
                {l.label}
              </Link>
              {l.ok ? null : <span className="text-fail">(could not load)</span>}
              {i < meta.looked_at.length - 1 ? <span aria-hidden>;</span> : null}
            </span>
          ))}
        </div>
      ) : (
        <div className="text-xs text-ink-faint">Answered without looking anything up.</div>
      )}
    </div>
  );
}

function Chat({ companyId, periodId }: { companyId: string; periodId: string | null }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [turns, sending]);

  async function send(question: string) {
    const text = question.trim();
    if (!text || sending) return;
    const next: Turn[] = [...turns, { role: "user", text }];
    setTurns(next);
    setDraft("");
    setError(null);
    setSending(true);
    let start = Math.max(0, next.length - MAX_SENT);
    if (next[start].role !== "user") start += 1;
    try {
      const result = await api<AiAnswer>("ai/ask", {
        method: "POST",
        body: { companyId, periodId: periodId ?? undefined, messages: next.slice(start).map((t) => ({ role: t.role, text: t.text })) },
      });
      setTurns([...next, { role: "assistant", text: result.answer, meta: result }]);
    } catch (err) {
      // Take the question back out so it can be edited and sent again.
      setTurns(turns);
      setDraft(text);
      setError(errorMessage(err));
    } finally {
      setSending(false);
      field.current?.focus();
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send(draft);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Ask about these books"
        description="I can look things up and explain them. I cannot post, approve or change anything."
        actions={
          turns.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={() => { setTurns([]); setError(null); }} disabled={sending}>
              New conversation
            </Button>
          ) : null
        }
      />
      <CardBody className="space-y-4">
        <div className="space-y-4" role="log" aria-live="polite" aria-label="Conversation">
          {turns.length === 0 ? (
            <div className="space-y-3">
              <p className="text-sm text-ink-soft">
                Ask in plain words. Every figure I give comes from your books, and anything I could not find in them is flagged under the answer.
              </p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => void send(example)}
                    disabled={sending}
                    className="rounded-full border border-rule bg-paper px-3 py-1.5 text-left text-xs text-ink-soft hover:border-ledger hover:text-ledger-dark disabled:opacity-50"
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {turns.map((turn, i) =>
            turn.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] whitespace-pre-wrap rounded-lg bg-ledger-soft px-3.5 py-2.5 text-sm text-ink">{turn.text}</div>
              </div>
            ) : (
              <div key={i} className="max-w-[95%] rounded-lg border border-rule bg-card px-4 py-3">
                <Rich text={turn.text} />
                {turn.meta ? <AnswerNotes meta={turn.meta} /> : null}
              </div>
            ),
          )}
          {sending ? <Loading label="Looking it up..." /> : null}
          <div ref={bottom} />
        </div>

        {error ? <Notice kind="error">{error}</Notice> : null}

        <form onSubmit={onSubmit} className="space-y-2">
          <label htmlFor="ask-input" className="sr-only">
            Your question
          </label>
          <Textarea
            ref={field}
            id="ask-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={MAX_QUESTION}
            placeholder="For example: why did expenses go up this period?"
            disabled={sending}
            rows={2}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-ink-faint">
              Your question and the figures needed to answer it are sent to Anthropic&apos;s AI service. Enter to send, Shift+Enter for a new line.
            </p>
            <Button type="submit" loading={sending} disabled={draft.trim() === ""}>
              Ask
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

function AssistantLoader({ companyId, periodId }: { companyId: string; periodId: string | null }) {
  const { data, error, loading } = useApi<AiStatus>("ai/status");
  if (loading && !data) return <Loading />;
  if (error) return <Notice kind="error">{error}</Notice>;
  if (!data?.enabled) {
    return (
      <Notice kind="info">
        The assistant is switched off. The administrator needs to set <code>ANTHROPIC_API_KEY</code> on the API server and restart it.
      </Notice>
    );
  }
  return <Chat key={companyId} companyId={companyId} periodId={periodId} />;
}

export default function AssistantPage() {
  return (
    <>
      <PageHeader
        title="Ask Milaan"
        description="Ask questions about this company's books in plain words. The assistant only looks: it uses the same figures and the same access rules as every other screen."
      />
      <Gate>{({ company, period }) => <AssistantLoader companyId={company.id} periodId={period?.id ?? null} />}</Gate>
    </>
  );
}