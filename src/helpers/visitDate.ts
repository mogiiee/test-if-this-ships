// TEST FIXTURE — clean on purpose
import type { AppointmentDetails } from "appt-bridge-core";
import { AuditError } from "appt-bridge-core";
import { payloadString } from "./baseAppointmentHelper";

export function visitDateFrom(details: AppointmentDetails): string {
  const visitDate = payloadString(details, "visitDate");
  if (!visitDate) {
    throw new AuditError("visitDate is missing on details.payload");
  }
  return visitDate;
}
