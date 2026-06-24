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
import { useNavigate, useParams, useSearchParams } from "react-router";

import {
  cancelResearch,
  getResearch,
  getSources,
  listCompanies,
  listResearchRuns,
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
  hasTerminalEvent,
  parseResearchEvent,
  type ResearchEvent,
  researchEventTypes,
} from "./events";
import {
  loadResearchIndex,
  loadTrace,
  researchTitleFromQuestion,
  storeTrace,
  type StoredResearch,
  upsertResearchIndex,
} from "./storage";
import { selectRunsForThread } from "./threadRuns";

type ConnectionState = "idle" | "connecting" | "live" | "reconnecting" | "closed";

export type EvidenceFocus = {
  evidenceId: string;
  runId: string;
  requestId: number;
};

type ResearchMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  runId: string;
  createdAt: Date;
  status: ResearchRun["status"];
};

type ResearchContextValue = {
  researchId: string | null;
  researches: StoredResearch[];
  runs: ResearchRun[];
  selectedRun: ResearchRun | null;
  selectedRunId: string | null;
  activeRun: ResearchRun | null;
  events: ResearchEvent[];
  sources: ResearchSource[];
  companies: Company[];
  connection: ConnectionState;
  isLoading: boolean;
  inspector: "trace" | "sources";
  inspectorOpen: boolean;
  setInspector: (value: "trace" | "sources") => void;
  closeInspector: () => void;
  toggleInspector: (value: "trace" | "sources", runId: string) => void;
  evidenceFocus: EvidenceFocus | null;
  focusEvidence: (evidenceId: string, runId: string) => void;
  start: (question: string) => Promise<void>;
  cancel: () => Promise<void>;
  retry: () => Promise<void>;
  feedback: (rating: FeedbackRating) => Promise<void>;
  selectResearch: (researchId: string) => void;
  selectRun: (runId: string) => void;
  newResearch: () => void;
};

const ResearchContext = createContext<ResearchContextValue | null>(null);

const queryKeys = {
  history: (researchId: string) => ["research", "history", researchId] as const,
  run: (runId: string) => ["research", "run", runId] as const,
  sources: (runId: string) => ["research", "sources", runId] as const,
  companies: ["companies"] as const,
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

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
        ? hasTerminalEvent(stored)
          ? "closed"
          : "connecting"
        : "idle";

  useEffect(() => {
    if (!runId || !hasTerminalEvent(stored)) return;
    onTerminal();
  }, [onTerminal, runId, stored]);

  useEffect(() => {
    if (!runId) return;
    if (hasTerminalEvent(stored)) {
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

function mergeSelectedRun(
  runs: ResearchRun[],
  selected: ResearchRun | undefined,
  researchId: string | null,
): ResearchRun[] {
  if (!selected || runs.some((run) => run.run_id === selected.run_id)) return runs;
  if (researchId && selected.session_id !== researchId) return runs;
  return [...runs, selected].toSorted((left, right) =>
    left.queued_at.localeCompare(right.queued_at),
  );
}

function latestRunTimestamp(run: ResearchRun): string {
  return run.completed_at ?? run.started_at ?? run.queued_at;
}

function activeRunFor(runs: ResearchRun[]): ResearchRun | null {
  return runs.find((run) => !isTerminal(run.status)) ?? null;
}

function latestRunFor(runs: ResearchRun[]): ResearchRun | null {
  return runs.at(-1) ?? null;
}

function upsertResearchFromRuns(
  researchId: string,
  runs: ResearchRun[],
): StoredResearch[] | null {
  if (runs.length === 0) return null;
  const ordered = [...runs].toSorted((left, right) => left.queued_at.localeCompare(right.queued_at));
  const first = ordered[0]!;
  const latest = ordered[ordered.length - 1]!;
  const active = activeRunFor(ordered);
  return upsertResearchIndex({
    researchId,
    title: researchTitleFromQuestion(first.question),
    lastRunId: latest.run_id,
    lastQuestion: latest.question,
    status: active?.status ?? latest.status,
    createdAt: first.queued_at,
    updatedAt: latestRunTimestamp(latest),
  });
}

export function ResearchProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const params = useParams<{ researchId?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const routeResearchId = params.researchId ?? null;
  const legacyRunId =
    routeResearchId && routeResearchId !== "new" && UUID_PATTERN.test(routeResearchId)
      ? routeResearchId
      : null;
  const researchId = routeResearchId === "new" || legacyRunId ? null : routeResearchId;
  const requestedRunId = searchParams.get("run");
  const queryClient = useQueryClient();
  const [researches, setResearches] = useState<StoredResearch[]>(() => loadResearchIndex());
  const [inspector, setInspector] = useState<"trace" | "sources">("trace");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [evidenceFocus, setEvidenceFocus] = useState<EvidenceFocus | null>(null);

  const historyQuery = useQuery({
    queryKey: queryKeys.history(researchId ?? "none"),
    queryFn: () => listResearchRuns(researchId!),
    enabled: researchId !== null,
  });

  const legacyRunQuery = useQuery({
    queryKey: queryKeys.run(legacyRunId ?? "none"),
    queryFn: () => getResearch(legacyRunId!),
    enabled: legacyRunId !== null,
  });

  const historyRuns = useMemo(
    () => [...(historyQuery.data?.items ?? [])].toSorted((left, right) =>
      left.queued_at.localeCompare(right.queued_at),
    ),
    [historyQuery.data?.items],
  );
  const activeRun = activeRunFor(historyRuns);
  const latestRun = latestRunFor(historyRuns);
  const selectedRunId = requestedRunId ?? activeRun?.run_id ?? latestRun?.run_id ?? legacyRunId;

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
    const refreshes = [
      queryClient.invalidateQueries({ queryKey: queryKeys.run(selectedRunId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.sources(selectedRunId) }),
    ];
    if (researchId) {
      refreshes.push(queryClient.invalidateQueries({ queryKey: queryKeys.history(researchId) }));
    }
    void Promise.all(refreshes);
  }, [queryClient, researchId, selectedRunId]);

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
    () => mergeSelectedRun(historyRuns, runQuery.data, researchId),
    [historyRuns, researchId, runQuery.data],
  );
  const selectedRun = runQuery.data ?? runs.find((run) => run.run_id === selectedRunId) ?? null;
  const currentActiveRun = activeRun ?? (
    selectedRun && !isTerminal(selectedRun.status) ? selectedRun : null
  );
  const threadRuns = useMemo(
    () => selectRunsForThread(runs, selectedRunId),
    [runs, selectedRunId],
  );

  const messages = useMemo<ResearchMessage[]>(() => {
    const result: ResearchMessage[] = [];
    for (const run of threadRuns) {
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
  }, [selectedRunId, streamedAnswer, threadRuns]);

  useEffect(() => {
    const run = legacyRunQuery.data;
    if (!legacyRunId || !run) return;
    let cancelled = false;
    const nextResearches = upsertResearchIndex({
      researchId: run.session_id,
      title: researchTitleFromQuestion(run.question),
      lastRunId: run.run_id,
      lastQuestion: run.question,
      status: run.status,
      createdAt: run.queued_at,
      updatedAt: latestRunTimestamp(run),
    });
    queueMicrotask(() => {
      if (cancelled) return;
      setResearches(nextResearches);
      void navigate(`/research/${run.session_id}?run=${run.run_id}`, { replace: true });
    });
    return () => {
      cancelled = true;
    };
  }, [legacyRunId, legacyRunQuery.data, navigate]);

  useEffect(() => {
    if (!researchId) return;
    const nextResearches = upsertResearchFromRuns(researchId, runs);
    if (!nextResearches) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setResearches(nextResearches);
    });
    return () => {
      cancelled = true;
    };
  }, [researchId, runs]);

  const startMutation = useMutation({
    mutationFn: (question: string) => startResearch(question, researchId),
  });
  const cancelMutation = useMutation({ mutationFn: cancelResearch });
  const feedbackMutation = useMutation({
    mutationFn: ({ runId, rating }: { runId: string; rating: FeedbackRating }) =>
      submitFeedback(runId, rating),
  });

  const start = async (question: string) => {
    const clean = question.trim();
    if (!clean) return;
    const accepted = await startMutation.mutateAsync(clean);
    setResearches(upsertResearchIndex({
      researchId: accepted.session_id,
      title: researchTitleFromQuestion(clean),
      lastRunId: accepted.run_id,
      lastQuestion: clean,
      status: accepted.status,
      updatedAt: new Date().toISOString(),
    }));
    await queryClient.invalidateQueries({ queryKey: queryKeys.history(accepted.session_id) });
    void navigate(`/research/${accepted.session_id}?run=${accepted.run_id}`);
    setInspector("trace");
    setInspectorOpen(false);
  };

  const cancel = async () => {
    const cancellableRunId = currentActiveRun?.run_id ?? selectedRunId;
    if (!cancellableRunId) return;
    await cancelMutation.mutateAsync(cancellableRunId);
    refreshRun();
  };

  const retry = async () => {
    if (selectedRun) await start(selectedRun.question);
  };

  const feedback = async (rating: FeedbackRating) => {
    if (!selectedRunId) return;
    await feedbackMutation.mutateAsync({ runId: selectedRunId, rating });
  };

  const inspectRun = useCallback((runId: string) => {
    if (!researchId) return;
    setSearchParams({ run: runId });
  }, [researchId, setSearchParams]);

  const toggleInspector = useCallback((value: "trace" | "sources", runId: string) => {
    if (inspectorOpen && inspector === value && selectedRunId === runId) {
      setInspectorOpen(false);
      return;
    }
    inspectRun(runId);
    setInspector(value);
    setInspectorOpen(true);
  }, [inspectRun, inspector, inspectorOpen, selectedRunId]);

  const focusEvidence = useCallback((evidenceId: string, runId: string) => {
    inspectRun(runId);
    setInspector("sources");
    setInspectorOpen(true);
    setEvidenceFocus((current) => ({
      evidenceId,
      runId,
      requestId: (current?.requestId ?? 0) + 1,
    }));
  }, [inspectRun]);

  const runtime = useExternalStoreRuntime<ResearchMessage>({
    messages,
    isLoading: historyQuery.isLoading || runQuery.isLoading || legacyRunQuery.isLoading,
    isRunning: currentActiveRun !== null,
    isSendDisabled: currentActiveRun !== null,
    convertMessage: toThreadMessage,
    onNew: async (message) => start(textFromMessage(message)),
    onCancel: cancel,
    onReload: async () => retry(),
  });

  const value: ResearchContextValue = {
    researchId,
    researches,
    runs,
    selectedRun,
    selectedRunId,
    activeRun: currentActiveRun,
    events,
    sources: sourcesQuery.data?.sources ?? selectedRun?.result?.sources ?? [],
    companies: companiesQuery.data?.items ?? [],
    connection,
    isLoading: historyQuery.isLoading || runQuery.isLoading || legacyRunQuery.isLoading,
    inspector,
    inspectorOpen,
    setInspector: (value) => {
      setInspector(value);
      setInspectorOpen(true);
    },
    closeInspector: () => setInspectorOpen(false),
    toggleInspector,
    evidenceFocus: evidenceFocus?.runId === selectedRunId ? evidenceFocus : null,
    focusEvidence,
    start,
    cancel,
    retry,
    feedback,
    selectResearch: (nextResearchId) => {
      setEvidenceFocus(null);
      setInspector("trace");
      setInspectorOpen(false);
      void navigate(`/research/${nextResearchId}`);
    },
    selectRun: (runId) => {
      setEvidenceFocus(null);
      inspectRun(runId);
    },
    newResearch: () => {
      setInspector("trace");
      setInspectorOpen(false);
      setEvidenceFocus(null);
      void navigate("/research/new");
    },
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
