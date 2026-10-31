import { setupWorker } from "msw/browser";

import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);

/** Start intercepting `/api/*` in the browser. Everything else (assets, RSC) passes through. */
export async function startMockWorker() {
  await worker.start({ onUnhandledFrame: "bypass", quiet: true });
}
