export function clearSupersededRejection<TAttempt extends { status: string; body: unknown }>(
  attempt: TAttempt | null,
  nextBody: unknown,
): TAttempt | null {
  if (attempt?.status === "rejected" && JSON.stringify(attempt.body) !== JSON.stringify(nextBody)) return null;
  return attempt;
}
