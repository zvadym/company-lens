export function selectRunsForThread<T extends { run_id: string; queued_at?: string }>(
  runs: T[],
  selectedRunId: string | null,
): T[] {
  if (!selectedRunId) return [];
  if (!runs.some((run) => run.run_id === selectedRunId)) return [];
  return [...runs].toSorted((left, right) => {
    if (!left.queued_at || !right.queued_at) return 0;
    return left.queued_at.localeCompare(right.queued_at);
  });
}
