import type { AppointmentDetails, Page, VerifyResult } from "appt-bridge-core";
import { AuditError } from "appt-bridge-core";
import { payloadString, waitForGrid } from "./baseAppointmentHelper";

export async function verifyAppointment(
  page: Page,
  details: AppointmentDetails,
): Promise<VerifyResult> {
  const visitDate = payloadString(details, "visitDate");
  const patientName = payloadString(details, "patientName");
  if (!visitDate || !patientName) {
    throw new AuditError("verify is missing visitDate or patientName on details.payload");
  }

  await page.getByPlaceholder("Search patients").fill(patientName);
  await page.getByRole("button", { name: "Search" }).click();
  await waitForGrid(page);

  const row = page.getByRole("row").filter({ hasText: visitDate });
  const exists = await row.count().then((n) => n > 0);

  if (!exists) {
    return {
      exists: false,
      isRequestChanged: false,
      rescheduleAllowed: true,
    };
  }

  const status = (await row.getByTestId("appt-status").innerText()).trim();
  const bookedDate = (await row.getByTestId("appt-date").innerText()).trim();
  const isRequestChanged = bookedDate !== visitDate;
  const rescheduleAllowed = status !== "Checked in" && status !== "Completed";

  return { exists: true, isRequestChanged, rescheduleAllowed };
}
