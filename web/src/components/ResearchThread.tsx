import {
  MessagePrimitive,
  ThreadPrimitive,
  useMessage,
} from "@assistant-ui/react";
import {
  ArrowDown,
  Ban,
  CheckCircle2,
  Copy,
  FileText,
  RotateCcw,
  SearchCode,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";

import { isTerminal, type ResearchRun } from "@/api/types";
import { useResearch } from "@/research/context";

import { AnswerCompanyBadges } from "./AnswerCompanyBadges";
import { ResearchComposer } from "./ResearchComposer";
import { groupEvidenceSources } from "./sourcePresentation";
import { WelcomePanel } from "./WelcomePanel";

const ResearchChart = lazy(() => import("./ResearchChart"));
const MarkdownText = lazy(() => import("./MarkdownText"));

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
      <AnswerCompanyBadges companies={run?.result?.answer_companies ?? []} />
      {run?.result?.chart ? (
        <Suspense fallback={<div className="chart-loading">Preparing chart…</div>}>
          <ResearchChart chart={run.result.chart} />
        </Suspense>
      ) : null}
    </MessagePrimitive.Root>
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
        <WelcomePanel />
        <Suspense fallback={<div className="message-loading">Formatting research answer…</div>}>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        </Suspense>
        {selectedRun && !isTerminal(selectedRun.status) ? (
          <div className="researching-indicator" role="status">
            <span /><span /><span /> {runningLabel}
          </div>
        ) : null}
        <RunStatusCard />
        <ThreadPrimitive.ViewportFooter className="thread-footer">
          {selectedRun ? (
            <ThreadPrimitive.ScrollToBottom className="scroll-button" aria-label="Scroll to latest message">
              <ArrowDown size={16} />
            </ThreadPrimitive.ScrollToBottom>
          ) : null}
          <ResearchComposer />
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}
