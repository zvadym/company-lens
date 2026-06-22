export function selectRunsForThread<T extends { run_id: string }>(
  runs: T[],
  selectedRunId: string | null,
): T[] {
  if (!selectedRunId) return [];
  const selectedRun = runs.find((run) => run.run_id === selectedRunId);
  return selectedRun ? [selectedRun] : [];
}
