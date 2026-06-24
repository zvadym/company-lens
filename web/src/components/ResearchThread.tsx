import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useMessage,
} from "@assistant-ui/react";
import {
  ArrowDown,
  ArrowUp,
  Ban,
  BookOpen,
  CheckCircle2,
  Copy,
  FileText,
  RotateCcw,
  SearchCode,
  Sparkles,
  Square,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";

import { isTerminal, type ResearchRun } from "@/api/types";
import { useResearch } from "@/research/context";

import { groupEvidenceSources } from "./sourcePresentation";

const ResearchChart = lazy(() => import("./ResearchChart"));
const MarkdownText = lazy(() => import("./MarkdownText"));

const prompts = [
  "Compare Cloudflare revenue growth over the last eight quarters.",
  "What are the most material risks management reported this year?",
  "Plot Cloudflare revenue growth against the federal funds rate.",
];

function useNow(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [enabled]);

  return now;
}

function formatRunStartedAt(run: ResearchRun | undefined): string {
  if (!run) return "Research response";
  const startedAt = run.started_at ?? run.queued_at;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(startedAt));
}

function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remainingSeconds.toString().padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes.toString().padStart(2, "0")}m`;
}

function runElapsedMs(run: ResearchRun, now: number): number {
  const startedAt = new Date(run.started_at ?? run.queued_at).getTime();
  const finishedAt = run.completed_at ? new Date(run.completed_at).getTime() : now;
  return finishedAt - startedAt;
}

function extractMessageText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (part && typeof part === "object" && "text" in part) {
        const text = (part as { text?: unknown }).text;
        return typeof text === "string" ? text : "";
      }
      return "";
    })
    .filter(Boolean)
    .join("\n")
    .trim();
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="message message-user">
      <div className="message-label">Research question</div>
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  const runId = useMessage((message) => {
    const custom = message.metadata.custom as { runId?: unknown };
    return typeof custom.runId === "string" ? custom.runId : null;
  });
  const messageText = useMessage((message) => extractMessageText(message.content));
  const { runs, inspector, inspectorOpen, selectedRunId, toggleInspector } = useResearch();
  const run = runs.find((item) => item.run_id === runId);
  const running = run ? !isTerminal(run.status) : false;
  const now = useNow(running);
  const answerText = messageText || run?.result?.answer?.trim() || "";
  const elapsed = run ? formatElapsed(runElapsedMs(run, now)) : null;
  const citations = run?.result?.citations ?? [];
  const sourceCount = groupEvidenceSources(run?.result?.sources ?? [], citations).length;
  const traceActive = inspectorOpen && selectedRunId === runId && inspector === "trace";
  const sourcesActive = inspectorOpen && selectedRunId === runId && inspector === "sources";
  return (
    <MessagePrimitive.Root className="message message-assistant">
      <div className="message-heading">
        <div className="message-meta">
          {run ? (
            <time dateTime={run.started_at ?? run.queued_at}>{formatRunStartedAt(run)}</time>
          ) : (
            <span>Research response</span>
          )}
          {elapsed ? <span>{running ? `${elapsed} elapsed` : elapsed}</span> : null}
        </div>
        <div className="message-actions">
          {runId ? (
            <>
              <button
                type="button"
                className={traceActive ? "is-active" : ""}
                onClick={() => toggleInspector("trace", runId)}
                aria-label={traceActive ? "Hide methodology" : "Show methodology"}
              >
                <SearchCode size={13} /> Trace
              </button>
              <button
                type="button"
                className={sourcesActive ? "is-active" : ""}
                onClick={() => toggleInspector("sources", runId)}
                aria-label={sourcesActive ? "Hide sources" : "Show sources"}
              >
                <FileText size={13} /> Sources <span>{sourceCount}</span>
              </button>
            </>
          ) : null}
          <button
            type="button"
            className="icon-button quiet"
            onClick={() => {
              if (answerText) void navigator.clipboard.writeText(answerText);
            }}
            aria-label="Copy answer text"
            disabled={!answerText}
          >
            <Copy size={14} />
          </button>
        </div>
      </div>
      <MessagePrimitive.Parts
        components={{
          Text: MarkdownText,
        }}
      />
    </MessagePrimitive.Root>
  );
}

function Welcome() {
  const { companies } = useResearch();
  const universe = companies
    .slice(0, 5)
    .map((company) => company.primary_ticker ?? company.display_name)
    .join(" · ");
  return (
    <ThreadPrimitive.Empty>
      <section className="welcome">
        <div className="welcome-kicker"><Sparkles size={14} /> Evidence-first company intelligence</div>
        <h1>Research that shows<br /><em>its working.</em></h1>
        <p>
          Ask a public-company question. CompanyLens will select the data path, expose every safe
          execution step, and validate the answer against its evidence.
        </p>
        {universe ? <div className="company-universe">Coverage · {universe}</div> : null}
        <div className="prompt-grid" aria-label="Example research questions">
          {prompts.map((prompt, index) => (
            <ThreadPrimitive.Suggestion key={prompt} prompt={prompt} send className="prompt-card">
              <span>0{index + 1}</span>
              <strong>{prompt}</strong>
              <ArrowUp size={16} />
            </ThreadPrimitive.Suggestion>
          ))}
        </div>
      </section>
    </ThreadPrimitive.Empty>
  );
}

function RunStatusCard() {
  const { selectedRun, retry, feedback } = useResearch();
  const [rated, setRated] = useState<"positive" | "negative" | null>(null);
  if (!selectedRun || !isTerminal(selectedRun.status)) return null;

  const successful = selectedRun.status === "completed" || selectedRun.status === "partial";
  const statusLabel = selectedRun.status === "abstained"
    ? selectedRun.result?.answer ? "Could not start" : "Could not answer"
    : selectedRun.status.replaceAll("_", " ");
  return (
    <section className={`run-outcome is-${selectedRun.status}`} aria-live="polite">
      <div>
        {successful ? <CheckCircle2 size={17} /> : <Ban size={17} />}
        <strong>{statusLabel}</strong>
        {selectedRun.error_message ? <span>{selectedRun.error_message}</span> : null}
      </div>
      <div className="outcome-actions">
        {!successful ? (
          <button type="button" onClick={() => void retry()}><RotateCcw size={14} /> Retry</button>
        ) : null}
        <button
          type="button"
          className={rated === "positive" ? "is-active" : ""}
          onClick={() => {
            setRated("positive");
            void feedback("positive");
          }}
          aria-label="Mark answer as helpful"
        ><ThumbsUp size={14} /></button>
        <button
          type="button"
          className={rated === "negative" ? "is-active" : ""}
          onClick={() => {
            setRated("negative");
            void feedback("negative");
          }}
          aria-label="Mark answer as unhelpful"
        ><ThumbsDown size={14} /></button>
      </div>
    </section>
  );
}

function Composer() {
  return (
    <ComposerPrimitive.Root className="composer">
      <div className="composer-topline">
        <span><BookOpen size={13} /> Research prompt</span>
        <span>Enter to send · Shift+Enter for a new line</span>
      </div>
      <ComposerPrimitive.Input
        className="composer-input"
        placeholder="Ask about filings, financial performance, risks, or macro context…"
        rows={2}
        submitMode="enter"
        aria-label="Research question"
      />
      <div className="composer-actions">
        <span>Answers include claim-level evidence</span>
        <ThreadPrimitive.If running>
          <ComposerPrimitive.Cancel className="send-button is-cancel" aria-label="Cancel research">
            <Square size={13} /> Stop
          </ComposerPrimitive.Cancel>
        </ThreadPrimitive.If>
        <ThreadPrimitive.If running={false}>
          <ComposerPrimitive.Send className="send-button" aria-label="Start research">
            Research <ArrowUp size={15} />
          </ComposerPrimitive.Send>
        </ThreadPrimitive.If>
      </div>
    </ComposerPrimitive.Root>
  );
}

export function ResearchThread() {
  const { selectedRun, events } = useResearch();
  const latestNodeEvent = [...events].reverse().find((event) => event.type === "node.status");
  const runningLabel = latestNodeEvent?.type === "node.status"
    && latestNodeEvent.data.status === "started"
    ? latestNodeEvent.data.summary
    : "Research graph is working";
  return (
    <ThreadPrimitive.Root className="thread-root">
      <ThreadPrimitive.Viewport className="thread-viewport" turnAnchor="top">
        <Welcome />
        <Suspense fallback={<div className="message-loading">Formatting research answer…</div>}>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        </Suspense>
        {selectedRun && !isTerminal(selectedRun.status) ? (
          <div className="researching-indicator" role="status">
            <span /><span /><span /> {runningLabel}
          </div>
        ) : null}
        {selectedRun?.result?.chart ? (
          <Suspense fallback={<div className="chart-loading">Preparing chart…</div>}>
            <ResearchChart chart={selectedRun.result.chart} />
          </Suspense>
        ) : null}
        <RunStatusCard />
        <ThreadPrimitive.ViewportFooter className="thread-footer">
          <ThreadPrimitive.ScrollToBottom className="scroll-button" aria-label="Scroll to latest message">
            <ArrowDown size={16} />
          </ThreadPrimitive.ScrollToBottom>
          <Composer />
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}
