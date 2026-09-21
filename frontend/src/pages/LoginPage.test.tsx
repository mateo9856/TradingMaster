import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { LoginPage } from "./LoginPage";
import { USER, signedIn } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")),
  useNavigate: () => navigate,
}));

async function fillIn(email = "trader@example.com", password = "supersecret123") {
  await userEvent.type(screen.getByLabelText("E-mail"), email);
  await userEvent.type(screen.getByLabelText("Password"), password);
}

describe("signing in", () => {
  it("stores the token and goes to the profile", async () => {
    server.use(
      http.post("/api/v1/auth/cookie/login", () => new HttpResponse(null, { status: 204 })),
      signedIn(),
    );
    renderApp(<LoginPage />);

    await fillIn();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/profile"));
    // Nothing token-shaped is left in the page — the session is an http-only cookie.
    expect(localStorage.length).toBe(0);
  });

  it("shows a plain message for wrong credentials", async () => {
    server.use(
      http.post("/api/v1/auth/cookie/login", () =>
        HttpResponse.json({ detail: "LOGIN_BAD_CREDENTIALS" }, { status: 400 }),
      ),
    );
    renderApp(<LoginPage />);

    await fillIn("trader@example.com", "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Wrong e-mail or password.")).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
  });

  it("reports an unreachable API", async () => {
    server.use(http.post("/api/v1/auth/cookie/login", () => HttpResponse.error()));
    renderApp(<LoginPage />);

    await fillIn();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText(/Cannot reach the TradingMaster API|Failed to fetch/i)).toBeInTheDocument();
  });
});

describe("registering", () => {
  it("creates the account then signs straight in", async () => {
    const calls: string[] = [];
    server.use(
      http.post("/api/v1/auth/register", async ({ request }) => {
        calls.push("register");
        expect(await request.json()).toEqual({
          email: "new@example.com",
          password: "supersecret123",
        });
        return HttpResponse.json(USER, { status: 201 });
      }),
      http.post("/api/v1/auth/cookie/login", () => {
        calls.push("login");
        return new HttpResponse(null, { status: 204 });
      }),
      signedIn(),
    );
    renderApp(<LoginPage />);

    await userEvent.click(screen.getByRole("button", { name: /No account\? Register/ }));
    await fillIn("new@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(calls).toEqual(["register", "login"]));
  });

  it("reports a rejected registration", async () => {
    server.use(
      http.post("/api/v1/auth/register", () =>
        HttpResponse.json({ detail: "REGISTER_USER_ALREADY_EXISTS" }, { status: 400 }),
      ),
    );
    renderApp(<LoginPage />);

    await userEvent.click(screen.getByRole("button", { name: /No account\? Register/ }));
    await fillIn();
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(await screen.findByText(/REGISTER_USER_ALREADY_EXISTS/)).toBeInTheDocument();
  });
});
