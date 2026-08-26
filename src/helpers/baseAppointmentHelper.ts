import type { Page } from "appt-bridge-core";

export async function waitForGrid(page: Page): Promise<void> {
  await page.waitForTimeout(400);
  await page.waitForLoadState("networkidle");
}

export function payloadString(
  details: { payload?: Record<string, unknown> },
  key: string,
): string {
  const value = details.payload?.[key];
  return typeof value === "string" ? value.trim() : "";
}
