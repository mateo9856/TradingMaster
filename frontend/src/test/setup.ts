import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./server";

// The display currency follows the machine's time zone (src/lib/currency.ts).
// Pin it, so the suite gives the same answer in Warsaw as in CI; tests about
// detection set their own zone and language.
process.env.TZ = "UTC";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));

afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
});

afterAll(() => server.close());
