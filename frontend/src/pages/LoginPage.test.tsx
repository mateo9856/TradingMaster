import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "./LoginPage";
import { activateLanguage } from "@/lib/i18n";
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

async function fillRegistration(email = "trader@example.com", password = "supersecret123") {
  await fillIn(email, password);
  await userEvent.type(screen.getByLabelText("Repeat password"), password);
}

beforeEach(async () => {
  vi.clearAllMocks();
  await activateLanguage("en");
});

afterEach(async () => {
  await act(() => activateLanguage("en"));
});

describe("signing in", () => {
  it("starts a cookie session and goes to the profile", async () => {
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

    expect(await screen.findByText("Cannot reach TradingMaster. Check your connection and try again.")).toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });

  it("does not apply the registration password length limit to sign-in", async () => {
    server.use(
      http.post("/api/v1/auth/cookie/login", () => new HttpResponse(null, { status: 204 })),
      signedIn(),
    );
    renderApp(<LoginPage />);
    await fillIn("trader@example.com", "old");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/profile"));
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
    await fillRegistration("new@example.com");
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
    await fillRegistration();
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(await screen.findByText("An account with this e-mail address already exists.")).toBeInTheDocument();
    expect(screen.queryByText(/REGISTER_USER_ALREADY_EXISTS/)).not.toBeInTheDocument();
  });
});

describe("inline validation", () => {
  it("shows required errors, focuses the first invalid field, and sends no login request", async () => {
    const login = vi.fn(() => new HttpResponse(null, { status: 204 }));
    server.use(http.post("/api/v1/auth/cookie/login", login));
    renderApp(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByLabelText("E-mail")).toHaveFocus();
    expect(screen.getByLabelText("E-mail")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("E-mail")).toHaveAccessibleDescription("Enter your e-mail address.");
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription("Enter your password.");
    expect(screen.queryByLabelText("Repeat password")).not.toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("validates on blur and removes an error as the field is corrected", async () => {
    renderApp(<LoginPage />);
    await userEvent.type(screen.getByLabelText("E-mail"), "invalid");
    expect(screen.queryByText("Enter a valid e-mail address.")).not.toBeInTheDocument();
    await userEvent.tab();
    expect(screen.getByLabelText("E-mail")).toHaveAccessibleDescription("Enter a valid e-mail address.");
    await userEvent.type(screen.getByLabelText("E-mail"), "@example.com");
    expect(screen.queryByText("Enter a valid e-mail address.")).not.toBeInTheDocument();
    expect(screen.getByLabelText("E-mail")).toHaveAttribute("aria-invalid", "false");
  });

  it.each([
    ["", "supersecret123", "supersecret123", "Enter your e-mail address.", "E-mail"],
    ["invalid", "supersecret123", "supersecret123", "Enter a valid e-mail address.", "E-mail"],
    ["new@example.com", "", "supersecret123", "Enter your password.", "Password"],
    ["new@example.com", "short", "short", "Use a password with 12–128 characters.", "Password"],
    ["new@example.com", "x".repeat(129), "x".repeat(129), "Use a password with 12–128 characters.", "Password"],
    ["new@example.com", "supersecret123", "", "Repeat your password.", "Repeat password"],
    ["new@example.com", "supersecret123", "different12345", "The passwords do not match.", "Repeat password"],
  ])("blocks invalid registration: %s / %s / %s", async (email, password, repeat, message, focus) => {
    const register = vi.fn(() => HttpResponse.json(USER, { status: 201 }));
    server.use(http.post("/api/v1/auth/register", register));
    renderApp(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: /No account\? Register/ }));
    fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: email } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
    fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: repeat } });
    await userEvent.click(screen.getByRole("button", { name: "Register" }));
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.getByLabelText(focus)).toHaveFocus();
    expect(register).not.toHaveBeenCalled();
  });

  it("compares passwords exactly and submits their whitespace unchanged", async () => {
    const password = " supersecret123 ";
    let payload: unknown;
    server.use(
      http.post("/api/v1/auth/register", async ({ request }) => {
        payload = await request.json();
        return HttpResponse.json(USER, { status: 201 });
      }),
      http.post("/api/v1/auth/cookie/login", () => new HttpResponse(null, { status: 204 })),
      signedIn(),
    );
    renderApp(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: /No account\? Register/ }));
    await fillIn("new@example.com", password);
    await userEvent.type(screen.getByLabelText("Repeat password"), password.trim());
    await userEvent.click(screen.getByRole("button", { name: "Register" }));
    expect(screen.getByText("The passwords do not match.")).toBeInTheDocument();
    expect(payload).toBeUndefined();

    fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: password } });
    expect(screen.queryByText("The passwords do not match.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Register" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/profile"));
    expect(payload).toEqual({ email: "new@example.com", password });
  });

  it("rechecks confirmation when the original password changes", async () => {
    renderApp(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: /No account\? Register/ }));
    await fillRegistration();
    await userEvent.tab();
    await userEvent.type(screen.getByLabelText("Password"), "changed");
    expect(screen.getByLabelText("Repeat password")).toHaveAccessibleDescription("The passwords do not match.");
  });

  it("clears confirmation and validation when switching modes", async () => {
    renderApp(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: /No account\? Register/ }));
    await fillIn();
    await userEvent.type(screen.getByLabelText("Repeat password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));
    await userEvent.click(screen.getByRole("button", { name: /Already registered/ }));
    expect(screen.queryByLabelText("Repeat password")).not.toBeInTheDocument();
    expect(screen.queryByText("The passwords do not match.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /No account\? Register/ }));
    expect(screen.getByLabelText("Repeat password")).toHaveValue("");
    expect(screen.getByLabelText("Repeat password")).toHaveAttribute("aria-invalid", "false");
  });

  it("uses Polish messages and translates visible errors when the language changes", async () => {
    await activateLanguage("pl");
    renderApp(<LoginPage />, { route: "/pl/login" });
    await userEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));
    expect(screen.getByLabelText("E-mail")).toHaveAccessibleDescription("Podaj adres e-mail.");
    expect(screen.getByLabelText("Hasło")).toHaveAccessibleDescription("Podaj hasło.");

    await act(() => activateLanguage("en"));
    expect(screen.getByLabelText("E-mail")).toHaveAccessibleDescription("Enter your e-mail address.");
    expect(screen.queryByText("Podaj hasło.")).not.toBeInTheDocument();
  });

  it("confirms passwords in Polish and navigates to the Polish profile", async () => {
    await activateLanguage("pl");
    let registrations = 0;
    server.use(
      http.post("/api/v1/auth/register", () => { registrations++; return HttpResponse.json(USER, { status: 201 }); }),
      http.post("/api/v1/auth/cookie/login", () => new HttpResponse(null, { status: 204 })),
      signedIn(),
    );
    renderApp(<LoginPage />, { route: "/pl/login" });
    await userEvent.click(screen.getByRole("button", { name: "Nie masz konta? Zarejestruj się" }));
    await userEvent.type(screen.getByLabelText("E-mail"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Hasło"), "supersecret123");
    await userEvent.click(screen.getByRole("button", { name: "Zarejestruj się" }));
    expect(screen.getByLabelText("Powtórz hasło")).toHaveAccessibleDescription("Powtórz hasło.");
    expect(registrations).toBe(0);
    await userEvent.type(screen.getByLabelText("Powtórz hasło"), "different12345");
    await userEvent.tab();
    expect(screen.getByText("Hasła nie są takie same.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Powtórz hasło"), { target: { value: "supersecret123" } });
    await userEvent.click(screen.getByRole("button", { name: "Zarejestruj się" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/pl/profile"));
    expect(registrations).toBe(1);
  });
});

describe("translated API failures", () => {
  it.each([
    ["Password must be at least 12 characters.", "Use a password with 12–128 characters."],
    ["Password must be at most 128 characters.", "Use a password with 12–128 characters."],
    ["That password is too common. Choose something less guessable.", "This password is too common. Choose a less predictable password."],
    ["Password must not contain your email address.", "Your password must not contain your e-mail address or the part before @."],
    ["Password must not be your email address.", "Your password must not contain your e-mail address or the part before @."],
    ["Password must not be a single repeated character.", "Your password must not consist of a single repeated character."],
    ["An unknown policy reason", "This password is not allowed. Choose a stronger password."],
  ])("translates password rejection: %s", async (reason, message) => {
    server.use(http.post("/api/v1/auth/register", () => HttpResponse.json({
      detail: { code: "REGISTER_INVALID_PASSWORD", reason },
    }, { status: 400 })));
    renderApp(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: /No account\? Register/ }));
    await fillRegistration();
    await userEvent.click(screen.getByRole("button", { name: "Register" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it.each([
    [400, "LOGIN_USER_NOT_VERIFIED", "Verify your e-mail address before signing in."],
    [400, "UNEXPECTED_ERROR", "Could not sign in. Please try again."],
    [422, [{ loc: ["body", "email"], msg: "value is not a valid email address" }], "Check your e-mail address and password, then try again."],
    [429, "Too Many Requests", "Too many attempts. Please wait and try again."],
    [500, "Internal Server Error", "Could not sign in. Please try again."],
  ])("translates sign-in failures with status %s", async (status, detail, message) => {
    server.use(http.post("/api/v1/auth/cookie/login", () => HttpResponse.json({ detail }, { status })));
    renderApp(<LoginPage />);
    await fillIn();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("uses a translated fallback for unexpected registration failures", async () => {
    server.use(http.post("/api/v1/auth/register", () => HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 })));
    renderApp(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: /No account\? Register/ }));
    await fillRegistration();
    await userEvent.click(screen.getByRole("button", { name: "Register" }));
    expect(await screen.findByText("Could not create your account. Please try again.")).toBeInTheDocument();
    expect(screen.queryByText(/Internal Server Error/)).not.toBeInTheDocument();
  });

  it("updates an API error when the language changes", async () => {
    server.use(http.post("/api/v1/auth/cookie/login", () => HttpResponse.json({ detail: "LOGIN_BAD_CREDENTIALS" }, { status: 400 })));
    renderApp(<LoginPage />);
    await fillIn();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("Wrong e-mail or password.");
    await act(() => activateLanguage("pl"));
    expect(screen.getByText("Nieprawidłowy e-mail lub hasło.")).toBeInTheDocument();
    expect(screen.queryByText("Wrong e-mail or password.")).not.toBeInTheDocument();
  });
});
