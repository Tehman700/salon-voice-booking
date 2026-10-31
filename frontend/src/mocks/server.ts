import { setupServer } from "msw/node";

import { handlers } from "./handlers";

/** MSW for Vitest: the real API client runs against the same handlers as the browser. */
export const server = setupServer(...handlers);
