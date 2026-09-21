import { setupServer } from "msw/node";

import { handlers } from "./handlers";

/** Mock API used by every test; individual tests override with server.use(...). */
export const server = setupServer(...handlers);
