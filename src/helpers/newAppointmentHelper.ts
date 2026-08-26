import type { AppointmentDetails, Page } from "appt-bridge-core";
import { AuditError } from "appt-bridge-core";
import { payloadString, waitForGrid } from "./baseAppointmentHelper";

export async function createAppointment(
  page: Page,
  details: AppointmentDetails,
): Promise<{ status: "REQUESTED" | "CONFIRMED" }> {
  const visitDate = payloadString(details, "visitDate");
  const reasonCode = payloadString(details, "reasonCode");
  const slot = payloadString(details, "slot");
  if (!visitDate || !reasonCode || !slot) {
    throw new AuditError("create is missing visitDate, reasonCode, or slot on details.payload");
  }

  await page.getByRole("button", { name: "New appointment" }).click();
  await page.getByLabel("Visit date").fill(visitDate);
  await page.getByLabel("Reason").selectOption(reasonCode);
  await page.getByRole("radio", { name: slot }).check();
  await page.getByRole("button", { name: "Submit request" }).click();
  await waitForGrid(page);

  const banner = page.getByRole("status").or(page.getByTestId("submit-result"));
  await banner.waitFor();
  const text = (await banner.innerText()).trim();

  if (/confirmed/i.test(text)) {
    return { status: "CONFIRMED" };
  }
  if (/requested|pending/i.test(text)) {
    return { status: "REQUESTED" };
  }

  throw new AuditError(
    `create submitted but the portal did not confirm: ${text || "(empty banner)"}`,
  );
}
