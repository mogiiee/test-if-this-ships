// Intentionally broken — try/catch hides errors from ErrorClassifier.
export async function createAppointment(page: unknown, details: { originalRequest?: unknown }) {
  try {
    const id = (details as { originalRequest?: { id?: string } }).originalRequest?.id;
    if (!id) throw new Error("missing id");
    return { status: "REQUESTED" };
  } catch (e) {
    return { status: "REQUESTED" };
  }
}
