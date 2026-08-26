// TEST FIXTURE — broken on purpose for @if-this-ships
// Always-flag #2: try/catch in a helper (hides errors from ErrorClassifier)
// Always-flag #3: reads originalRequest (helpers get details.* only)
// Always-flag #4: throw new Error (should be AuditError)
// Always-flag #11: fake success — returns REQUESTED even when it failed

export async function createAppointment(
  page: unknown,
  details: { originalRequest?: { id?: string } },
) {
  try {
    const id = details.originalRequest?.id;
    if (!id) throw new Error("missing id");
    return { status: "REQUESTED" };
  } catch {
    return { status: "REQUESTED" };
  }
}
