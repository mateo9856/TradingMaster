
import { historyApi } from "@/features/history/api";

import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";



import { server } from "@/test/server";

describe("archive trigger", () => {
  it("posts the date and returns the accepted envelope", async () => {
    server.use(
      http.post("/api/v1/history/archive/:date", ({ params }) =>
        HttpResponse.json(
          { status: "accepted", message: `Archive job started for ${params.date}`, data: null },
          { status: 202 },
        ),
      ),
    );

    const response = await historyApi.triggerArchive("2026-09-19");

    expect(response.status).toBe("accepted");
    expect(response.message).toContain("2026-09-19");
  });

  it("surfaces the 401 when not signed in", async () => {
    server.use(
      http.post("/api/v1/history/archive/:date", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );

    const error = await historyApi.triggerArchive("2026-09-19").catch((e) => e);

    expect(error.isUnauthorized).toBe(true);
  });
});
