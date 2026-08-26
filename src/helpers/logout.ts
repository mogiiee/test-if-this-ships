// TEST FIXTURE — broken on purpose for @if-this-ships
// Always-flag #1: stub / missing logout
// Core always calls logout() then close(). This is a TODO no-op.

export async function logout() {
  // TODO: click the real site logout. Not implemented.
  return;
}
