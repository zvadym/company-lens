import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
} from "@assistant-ui/react";
import {
  ArrowDown,
  ArrowUp,
  Ban,
  BookOpen,
  CheckCircle2,
  Copy,
  RotateCcw,
  Sparkles,
  Square,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { lazy, Suspense, useState } from "react";

import { isTerminal } from "@/api/types";
import { useResearch } from "@/research/context";

const ResearchChart = lazy(() => import("./ResearchChart"));
const MarkdownText = lazy(() => import("./MarkdownText"));

const prompts = [
  "Compare Cloudflare revenue growth over the last eight quarters.",
  "What are the most material risks management reported this year?",
  "Plot Cloudflare revenue growth against the federal funds rate.",
];

function UserMessage() {
  return (
    <MessagePrimitive.Root className="message message-user">
      <div className="message-label">Research question</div>
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="message message-assistant">
      <div className="message-heading">
        <span>CompanyLens synthesis</span>
        <button
          type="button"
          className="icon-button quiet"
          onClick={() => void navigator.clipboard.writeText(window.getSelection()?.toString() ?? "")}
          aria-label="Copy selected answer text"
        >
          <Copy size={14} />
        </button>
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
