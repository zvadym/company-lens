import {
  AssistantRuntimeProvider,
  type AppendMessage,
  type ThreadMessageLike,
  useExternalStoreRuntime,
} from "@assistant-ui/react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useNavigate, useParams } from "react-router";

import {
  cancelResearch,
  getResearch,
  getSources,
  listCompanies,
  listResearch,
  startResearch,
  submitFeedback,
} from "@/api/client";
import type {
  Company,
  FeedbackRating,
  ResearchRun,
  ResearchSource,
} from "@/api/types";
import { isTerminal } from "@/api/types";

import {
  parseResearchEvent,
  type ResearchEvent,
  researchEventTypes,
} from "./events";
import { getSessionId, loadTrace, storeTrace } from "./storage";

type ConnectionState = "idle" | "connecting" | "live" | "reconnecting" | "closed";

type ResearchMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  runId: string;
  createdAt: Date;
  status: ResearchRun["status"];
};

type ResearchContextValue = {
  sessionId: string;
  runs: ResearchRun[];
  selectedRun: ResearchRun | null;
  selectedRunId: string | null;
  events: ResearchEvent[];
  sources: ResearchSource[];
  companies: Company[];
  connection: ConnectionState;
  isLoading: boolean;
  inspector: "trace" | "sources";
  setInspector: (value: "trace" | "sources") => void;
  start: (question: string) => Promise<void>;
  cancel: () => Promise<void>;
  retry: () => Promise<void>;
  feedback: (rating: FeedbackRating) => Promise<void>;
  selectRun: (runId: string) => void;
  newResearch: () => void;
};

const ResearchContext = createContext<ResearchContextValue | null>(null);

const queryKeys = {
  history: (sessionId: string) => ["research", "history", sessionId] as const,
  run: (runId: string) => ["research", "run", runId] as const,
  sources: (runId: string) => ["research", "sources", runId] as const,
  companies: ["companies"] as const,
};

function textFromMessage(message: AppendMessage): string {
  return message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n")
    .trim();
}

function toThreadMessage(message: ResearchMessage): ThreadMessageLike {
  const common = {
    id: message.id,
    role: message.role,
    content: [{ type: "text" as const, text: message.content }],
    createdAt: message.createdAt,
    metadata: { custom: { runId: message.runId, status: message.status } },
  };
  if (message.role === "user") return common;
  if (!isTerminal(message.status)) {
    return { ...common, status: { type: "running" } };
  }
  if (message.status === "completed" || message.status === "partial") {
    return { ...common, status: { type: "complete", reason: "stop" } };
  }
  return {
    ...common,
    status: {
      type: "incomplete",
      reason: message.status === "cancelled" ? "cancelled" : "error",
    },
  };
}

function useEventStream(
  runId: string | null,
  onTerminal: () => void,
): { events: ResearchEvent[]; connection: ConnectionState } {
  const stored = useMemo(() => (runId ? loadTrace(runId) : []), [runId]);
  const [eventState, setEventState] = useState<{
    runId: string | null;
    events: ResearchEvent[];
  }>({ runId: null, events: [] });
  const [connectionState, setConnectionState] = useState<{
    runId: string | null;
    value: ConnectionState;
  }>({ runId: null, value: "idle" });
  const events = eventState.runId === runId ? eventState.events : stored;
  const connection =
    connectionState.runId === runId
      ? connectionState.value
      : runId
        ? stored.some((event) => event.type === "run.terminal")
          ? "closed"
          : "connecting"
        : "idle";

  useEffect(() => {
    if (!runId) return;
    if (stored.some((event) => event.type === "run.terminal")) {
      return;
    }

    const cursor = stored.reduce((maximum, event) => Math.max(maximum, event.id), 0);
    const source = new EventSource(`/api/v1/research/${runId}/events?after_id=${cursor}`);

    const receive = (message: MessageEvent<string>) => {
      const event = parseResearchEvent(message.data);
      if (!event || event.run_id !== runId) return;
      setConnectionState({ runId, value: "live" });
      setEventState((current) => {
        const base = current.runId === runId ? current.events : stored;
        if (base.some((item) => item.id === event.id)) return { runId, events: base };
        const next = [...base, event].toSorted((left, right) => left.id - right.id);
        storeTrace(runId, next);
        return { runId, events: next };
      });
      if (event.type === "run.terminal") {
        setConnectionState({ runId, value: "closed" });
        source.close();
        onTerminal();
      }
    };

    for (const eventType of researchEventTypes) {
      source.addEventListener(eventType, receive as EventListener);
    }
    source.onopen = () => setConnectionState({ runId, value: "live" });
    source.onerror = () => setConnectionState({ runId, value: "reconnecting" });

    return () => source.close();
  }, [onTerminal, runId, stored]);

  return { events, connection };
}

function mergeSelectedRun(runs: ResearchRun[], selected: ResearchRun | undefined): ResearchRun[] {
  if (!selected || runs.some((run) => run.run_id === selected.run_id)) return runs;
  return [...runs, selected].toSorted((left, right) =>
    left.queued_at.localeCompare(right.queued_at),
  );
}

export function ResearchProvider({ children }: { children: ReactNode }) {
  const [sessionId] = useState(() => getSessionId());
  const navigate = useNavigate();
  const params = useParams<{ runId?: string }>();
  const selectedRunId = params.runId === "new" ? null : params.runId ?? null;
  const queryClient = useQueryClient();
  const [inspector, setInspector] = useState<"trace" | "sources">("trace");

  const historyQuery = useQuery({
    queryKey: queryKeys.history(sessionId),
    queryFn: () => listResearch(sessionId),
  });
  const runQuery = useQuery({
    queryKey: queryKeys.run(selectedRunId ?? "none"),
    queryFn: () => getResearch(selectedRunId!),
    enabled: selectedRunId !== null,
    refetchInterval: (query) => {
      const run = query.state.data;
      return run && !isTerminal(run.status) ? 3_000 : false;
    },
  });
  const sourcesQuery = useQuery({
    queryKey: queryKeys.sources(selectedRunId ?? "none"),
    queryFn: () => getSources(selectedRunId!),
    enabled: selectedRunId !== null,
  });
  const companiesQuery = useQuery({
    queryKey: queryKeys.companies,
    queryFn: listCompanies,
    staleTime: 5 * 60_000,
  });

  const refreshRun = useCallback(() => {
    if (!selectedRunId) return;
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.run(selectedRunId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.sources(selectedRunId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.history(sessionId) }),
    ]);
  }, [queryClient, selectedRunId, sessionId]);

  const { events, connection } = useEventStream(selectedRunId, refreshRun);
  const streamedAnswer = useMemo(
    () =>
      events
        .filter((event) => event.type === "answer.token")
        .toSorted((left, right) => left.data.index - right.data.index)
        .map((event) => event.data.delta)
        .join(""),
    [events],
  );

  const runs = useMemo(
    () => mergeSelectedRun(historyQuery.data?.items ?? [], runQuery.data),
    [historyQuery.data?.items, runQuery.data],
  );
  const selectedRun = runQuery.data ?? runs.find((run) => run.run_id === selectedRunId) ?? null;

  const messages = useMemo<ResearchMessage[]>(() => {
    const result: ResearchMessage[] = [];
    for (const run of runs) {
      result.push({
        id: `${run.run_id}:user`,
        role: "user",
        content: run.question,
        runId: run.run_id,
        createdAt: new Date(run.queued_at),
        status: run.status,
      });
      const liveAnswer = run.run_id === selectedRunId ? streamedAnswer : "";
      result.push({
        id: `${run.run_id}:assistant`,
        role: "assistant",
        content: run.result?.answer ?? liveAnswer,
        runId: run.run_id,
        createdAt: new Date(run.completed_at ?? run.started_at ?? run.queued_at),
        status: run.status,
      });
    }
    return result;
  }, [runs, selectedRunId, streamedAnswer]);

  const startMutation = useMutation({ mutationFn: (question: string) => startResearch(question, sessionId) });
  const cancelMutation = useMutation({ mutationFn: cancelResearch });
  const feedbackMutation = useMutation({
    mutationFn: ({ runId, rating }: { runId: string; rating: FeedbackRating }) =>
      submitFeedback(runId, rating),
  });

  const start = async (question: string) => {
    const clean = question.trim();
    if (!clean) return;
    const accepted = await startMutation.mutateAsync(clean);
    await queryClient.invalidateQueries({ queryKey: queryKeys.history(sessionId) });
    void navigate(`/research/${accepted.run_id}`);
    setInspector("trace");
  };

  const cancel = async () => {
    if (!selectedRunId) return;
    await cancelMutation.mutateAsync(selectedRunId);
    refreshRun();
  };

  const retry = async () => {
    if (selectedRun) await start(selectedRun.question);
  };

  const feedback = async (rating: FeedbackRating) => {
    if (!selectedRunId) return;
    await feedbackMutation.mutateAsync({ runId: selectedRunId, rating });
  };

  const runtime = useExternalStoreRuntime<ResearchMessage>({
    messages,
    isLoading: historyQuery.isLoading || runQuery.isLoading,
    isRunning: selectedRun ? !isTerminal(selectedRun.status) : false,
    isSendDisabled: selectedRun ? !isTerminal(selectedRun.status) : false,
    convertMessage: toThreadMessage,
    onNew: async (message) => start(textFromMessage(message)),
    onCancel: cancel,
    onReload: async () => retry(),
  });

  const value: ResearchContextValue = {
    sessionId,
    runs,
    selectedRun,
    selectedRunId,
    events,
    sources: sourcesQuery.data?.sources ?? selectedRun?.result?.sources ?? [],
    companies: companiesQuery.data?.items ?? [],
    connection,
    isLoading: historyQuery.isLoading || runQuery.isLoading,
    inspector,
    setInspector,
    start,
    cancel,
    retry,
    feedback,
    selectRun: (runId) => { void navigate(`/research/${runId}`); },
    newResearch: () => { void navigate("/research/new"); },
  };

  return (
    <ResearchContext.Provider value={value}>
      <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>
    </ResearchContext.Provider>
  );
}

// The provider and its colocated hook intentionally share one private context.
// eslint-disable-next-line react-refresh/only-export-components
export function useResearch(): ResearchContextValue {
  const context = useContext(ResearchContext);
  if (!context) throw new Error("useResearch must be used inside ResearchProvider");
  return context;
}
