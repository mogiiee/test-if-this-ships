import type { Page } from "appt-bridge-core";

export class NorthsideClinicBridge {
  constructor(private readonly page: Page) {}

  async logout(): Promise<void> {
    await this.page.getByRole("button", { name: "Account menu" }).click();
    await this.page.getByRole("menuitem", { name: "Sign out" }).click();
    await this.page.getByRole("heading", { name: "Sign in" }).waitFor();
  }
}
