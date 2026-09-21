import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { useAuth } from "./auth";
import { USER, signedIn } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

/** Minimal consumer of the auth context. */
function Session() {
  const { user, loading, login, logout } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const run = (action: () => Promise<void>) => () => {
    setError(null);
    action().catch((caught: Error) => setError(caught.message));
  };
  return (
    <div>
      <p data-testid="state">{loading ? "loading" : user ? `signed in: ${user.email}` : "signed out"}</p>
      <p data-testid="error">{error ?? ""}</p>
      <button onClick={run(() => login("trader@example.com", "supersecret123"))}>sign in</button>
      <button onClick={run(logout)}>sign out</button>
    </div>
  );
}

describe("restoring a session", () => {
  it("asks the API who we are, because the cookie is unreadable to the page", async () => {
    let asked = false;
    server.use(
      http.get("/api/v1/users/me", () => {
        asked = true;
        return HttpResponse.json(USER);
      }),
    );

    renderApp(<Session />);

    expect(await screen.findByText(`signed in: ${USER.email}`)).toBeInTheDocument();
    expect(asked).toBe(true);
  });

  it("treats a 401 as simply signed out — no error shown", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    renderApp(<Session />);

    expect(await screen.findByText("signed out")).toBeInTheDocument();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("stays signed out and logs the reason when the API is unreachable", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    server.use(http.get("/api/v1/users/me", () => HttpResponse.error()));

    renderApp(<Session />);

    expect(await screen.findByText("signed out")).toBeInTheDocument();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe("signing in and out", () => {
  it("signs in, then reflects the user from the API", async () => {
    server.use(http.post("/api/v1/auth/cookie/login", () => new HttpResponse(null, { status: 204 })));
    renderApp(<Session />);
    await screen.findByText("signed out");

    server.use(signedIn());
    await userEvent.click(screen.getByRole("button", { name: "sign in" }));

    expect(await screen.findByText(`signed in: ${USER.email}`)).toBeInTheDocument();
  });

  it("signs out through the API and clears the session", async () => {
    server.use(signedIn(), http.post("/api/v1/auth/cookie/logout", () => new HttpResponse(null, { status: 204 })));
    renderApp(<Session />);
    await screen.findByText(`signed in: ${USER.email}`);

    await userEvent.click(screen.getByRole("button", { name: "sign out" }));

    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("signed out"));
  });

  it("treats a 401 on sign-out as already signed out", async () => {
    server.use(
      signedIn(),
      http.post("/api/v1/auth/cookie/logout", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );
    renderApp(<Session />);
    await screen.findByText(`signed in: ${USER.email}`);

    await userEvent.click(screen.getByRole("button", { name: "sign out" }));

    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("signed out"));
    expect(screen.getByTestId("error")).toHaveTextContent("");
  });

  it("keeps the user signed in when sign-out genuinely fails", async () => {
    server.use(signedIn(), http.post("/api/v1/auth/cookie/logout", () => HttpResponse.error()));
    renderApp(<Session />);
    await screen.findByText(`signed in: ${USER.email}`);

    // The session may still be live on the server — don't claim it ended.
    await userEvent.click(screen.getByRole("button", { name: "sign out" }));

    await waitFor(() => expect(screen.getByTestId("error")).not.toHaveTextContent(""));
    expect(screen.getByTestId("state")).toHaveTextContent(`signed in: ${USER.email}`);
  });
});
