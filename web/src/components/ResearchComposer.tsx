import { ComposerPrimitive, ThreadPrimitive } from "@assistant-ui/react";
import { ArrowUp, BookOpen, Square } from "lucide-react";

export function ResearchComposer() {
  return (
    <ComposerPrimitive.Root className="composer">
      <div className="composer-topline">
        <span><BookOpen size={13} /> Research prompt</span>
      </div>
      <ComposerPrimitive.Input
        className="composer-input"
        placeholder="Ask about filings, financial performance, risks, or macro context..."
        rows={2}
        submitMode="enter"
        aria-label="Research question"
      />
      <div className="composer-actions">
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
