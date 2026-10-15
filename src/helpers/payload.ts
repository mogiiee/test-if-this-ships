export function payloadString(
  details: { payload?: Record<string, unknown> },
  key: string,
): string {
  const value = details.payload?.[key];
  return typeof value === "string" ? value.trim() : "";
}
