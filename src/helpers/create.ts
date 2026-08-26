// TEST FIXTURE — broken on purpose
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
