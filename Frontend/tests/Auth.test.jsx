import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import App from "../src/App";
import { fetchFeatureSchema } from "../src/api/client";

const USER = {
  id: "8d6f4c1e-0000-4000-8000-000000000001",
  name: "Ada Lovelace",
  username: "ada_l",
  email: "ada@example.com",
  profile_picture: null,
  created_at: "2026-10-01T12:00:00.000Z",
  updated_at: "2026-10-01T12:00:00.000Z",
  is_active: true,
};

function sessionBody(user = USER) {
  return {
    user,
    access_token: "header.payload.signature",
    token_type: "Bearer",
    expires_in: 600,
    access_token_expires_at: new Date(Date.now() + 600_000).toISOString(),
  };
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

/** Routes mocked fetch calls by "METHOD path"; records every call. */
function mockApi(handlers) {
  const fetchMock = vi.fn(async (url, options = {}) => {
    const path = new URL(url, "http://localhost").pathname;
    const key = `${options.method || "GET"} ${path}`;
    const handler = handlers[key];
    if (!handler) return jsonResponse(404, { error: { code: "NOT_FOUND", message: "not mocked" } });
    return handler(options);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function callsTo(fetchMock, method, path) {
  return fetchMock.mock.calls.filter(([url, opts = {}]) => (opts.method || "GET") === method && url.endsWith(path));
}

function setCsrfCookie(value) {
  document.cookie = `exo_csrf=${value}; path=/`;
}

function clearCookies() {
  document.cookie = "exo_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
}

function fill(label, value) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

beforeEach(() => {
  clearCookies();
  window.history.pushState({}, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  clearCookies();
});

describe("logged-out experience", () => {
  test("shows the Login / Sign Up entry and no account entries", () => {
    const fetchMock = mockApi({});
    render(<App />);
    expect(screen.getByRole("link", { name: "Login / Sign Up" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("link", { name: "User Dashboard" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Account:/ })).not.toBeInTheDocument();
    // No session cookie -> no pointless refresh request on page load.
    expect(callsTo(fetchMock, "POST", "/api/v1/auth/refresh")).toHaveLength(0);
  });

  test.each(["/", "/manual-parameters", "/results", "/physics-validation", "/characterisation", "/report"])(
    "the analysis page %s is not available until the user logs in",
    async (path) => {
      mockApi({});
      window.history.pushState({}, "", path);
      render(<App />);
      expect(await screen.findByRole("heading", { name: "Log In" })).toBeInTheDocument();
      expect(window.location.pathname).toBe("/login");
      expect(screen.queryByText(/Drag & drop an observational CSV here/i)).not.toBeInTheDocument();
      expect(document.querySelector('input[type="file"]')).toBeNull();
    }
  );

  test("System Status stays public", () => {
    mockApi({});
    window.history.pushState({}, "", "/status");
    render(<App />);
    expect(screen.getByRole("heading", { name: "System Status" })).toBeInTheDocument();
  });

  test("after logging in the user is returned to the upload page they tried to open", async () => {
    mockApi({ "POST /api/v1/auth/login": () => jsonResponse(200, sessionBody()) });
    render(<App />); // at "/"
    expect(await screen.findByRole("heading", { name: "Log In" })).toBeInTheDocument();
    fill("Email or username", "ada_l");
    fill("Password", "Nebula-Drift-42");
    fireEvent.click(screen.getByRole("button", { name: /Log in/i }));
    expect(await screen.findByRole("heading", { name: /^Upload Light Curve$/i })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
  });

  test("the private dashboard redirects to the login form", async () => {
    mockApi({});
    window.history.pushState({}, "", "/account");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Log In" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/login");
  });

  test("users can switch between the login and sign-up forms", () => {
    mockApi({});
    window.history.pushState({}, "", "/login");
    render(<App />);
    expect(screen.getByRole("form", { name: "Log in" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Sign up" }));
    expect(screen.getByRole("form", { name: "Sign up" })).toBeInTheDocument();
    expect(screen.getByLabelText("Confirm password")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Log in" }));
    expect(screen.getByRole("form", { name: "Log in" })).toBeInTheDocument();
  });
});

describe("sign-up", () => {
  beforeEach(() => window.history.pushState({}, "", "/signup"));

  test("validates required fields and matching passwords before calling the API", () => {
    const fetchMock = mockApi({});
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Create account/i }));
    expect(screen.getByText("Full name is required.")).toBeInTheDocument();
    expect(screen.getByText("Username is required.")).toBeInTheDocument();
    expect(screen.getByText("Email address is required.")).toBeInTheDocument();

    fill("Full name", "Ada Lovelace");
    fill("Username", "ada_l");
    fill("Email address", "ada@example.com");
    fill("Password", "Nebula-Drift-42");
    fill("Confirm password", "Nebula-Drift-43");
    fireEvent.click(screen.getByRole("button", { name: /Create account/i }));
    expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", "/api/v1/auth/register")).toHaveLength(0);
  });

  test("enforces password strength", () => {
    mockApi({});
    render(<App />);
    fill("Password", "short");
    fireEvent.click(screen.getByRole("button", { name: /Create account/i }));
    expect(screen.getByText(/at least 10 characters/i, { selector: ".auth-field-error" })).toBeInTheDocument();
  });

  test("shows the server's duplicate-email error on the email field", async () => {
    mockApi({
      "POST /api/v1/auth/register": () =>
        jsonResponse(409, {
          error: {
            code: "EMAIL_TAKEN",
            message: "An account with this email address already exists.",
            fields: { email: "An account with this email address already exists." },
          },
        }),
    });
    render(<App />);
    fill("Full name", "Ada Lovelace");
    fill("Username", "ada_l");
    fill("Email address", "ada@example.com");
    fill("Password", "Nebula-Drift-42");
    fill("Confirm password", "Nebula-Drift-42");
    fireEvent.click(screen.getByRole("button", { name: /Create account/i }));
    expect(await screen.findByText("An account with this email address already exists.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toHaveAttribute("aria-invalid", "true");
  });

  test("a successful sign-up signs the user in and opens their dashboard", async () => {
    const fetchMock = mockApi({
      "POST /api/v1/auth/register": () => jsonResponse(201, sessionBody()),
      "GET /api/v1/auth/me": () => jsonResponse(200, { user: USER }),
    });
    render(<App />);
    fill("Full name", "Ada Lovelace");
    fill("Username", "ada_l");
    fill("Email address", "ada@example.com");
    fill("Password", "Nebula-Drift-42");
    fill("Confirm password", "Nebula-Drift-42");
    fireEvent.click(screen.getByRole("button", { name: /Create account/i }));

    expect(await screen.findByRole("heading", { name: "User Dashboard" })).toBeInTheDocument();
    const [, options] = callsTo(fetchMock, "POST", "/api/v1/auth/register")[0];
    expect(JSON.parse(options.body)).toEqual({
      name: "Ada Lovelace",
      username: "ada_l",
      email: "ada@example.com",
      password: "Nebula-Drift-42",
      confirm_password: "Nebula-Drift-42",
    });
    expect(screen.getByRole("link", { name: "User Dashboard" })).toBeInTheDocument();
  });
});

describe("login", () => {
  beforeEach(() => window.history.pushState({}, "", "/login"));

  test("shows the generic error for bad credentials and clears the password", async () => {
    mockApi({
      "POST /api/v1/auth/login": () =>
        jsonResponse(401, { error: { code: "INVALID_CREDENTIALS", message: "Incorrect email/username or password." } }),
    });
    render(<App />);
    fill("Email or username", "ada@example.com");
    fill("Password", "wrong-password-1");
    fireEvent.click(screen.getByRole("button", { name: /Log in/i }));
    expect(await screen.findByText("Incorrect email/username or password.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByRole("link", { name: "Login / Sign Up" })).toBeInTheDocument();
  });

  test("a successful login shows the profile entry and dashboard in the dock", async () => {
    const fetchMock = mockApi({
      "POST /api/v1/auth/login": () => jsonResponse(200, sessionBody()),
      "GET /api/v1/auth/me": () => jsonResponse(200, { user: USER }),
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(<App />);
    fill("Email or username", "ada_l");
    fill("Password", "Nebula-Drift-42");
    fireEvent.click(screen.getByRole("button", { name: /Log in/i }));

    expect(await screen.findByRole("heading", { name: "User Dashboard" })).toBeInTheDocument();
    const dock = screen.getByLabelText("Primary navigation");
    expect(within(dock).getByRole("link", { name: "User Dashboard" })).toHaveAttribute("href", "/account");
    expect(within(dock).getByRole("link", { name: "Account: Ada Lovelace" })).toHaveAttribute("href", "/account");
    expect(within(dock).queryByRole("link", { name: "Login / Sign Up" })).not.toBeInTheDocument();
    // Existing navigation is untouched.
    expect(within(dock).getByRole("link", { name: "Upload & Analyze" })).toHaveAttribute("href", "/");
    expect(within(dock).getByRole("link", { name: "System Status" })).toHaveAttribute("href", "/status");

    // The access token is sent as a Bearer header and never written to web storage.
    // The dashboard heading renders before its profile request (sent from an
    // effect after the token is resolved), so wait for the request itself.
    await waitFor(() => expect(callsTo(fetchMock, "GET", "/api/v1/auth/me")).toHaveLength(1));
    const [, meOptions] = callsTo(fetchMock, "GET", "/api/v1/auth/me")[0];
    expect(meOptions.headers.Authorization).toBe("Bearer header.payload.signature");
    expect(setItem).not.toHaveBeenCalledWith(expect.anything(), expect.stringContaining("header.payload.signature"));
    setItem.mockRestore();
  });
});

describe("analysis requests while signed in", () => {
  test("analysis API calls carry the in-memory access token", async () => {
    setCsrfCookie("csrf-token-value");
    const fetchMock = mockApi({
      "POST /api/v1/auth/refresh": () => jsonResponse(200, sessionBody()),
      "GET /api/v1/feature-schema": () => jsonResponse(200, { features: [] }),
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: /^Upload Light Curve$/i })).toBeInTheDocument();
    await fetchFeatureSchema();
    const [, options] = callsTo(fetchMock, "GET", "/api/v1/feature-schema")[0];
    expect(options.headers.Authorization).toBe("Bearer header.payload.signature");
  });
});

describe("session persistence, dashboard and logout", () => {
  test("a page reload restores the session from the refresh cookie", async () => {
    setCsrfCookie("csrf-token-value");
    const fetchMock = mockApi({
      "POST /api/v1/auth/refresh": () => jsonResponse(200, sessionBody()),
      "GET /api/v1/auth/me": () => jsonResponse(200, { user: USER }),
    });
    window.history.pushState({}, "", "/account");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    const [, refreshOptions] = callsTo(fetchMock, "POST", "/api/v1/auth/refresh")[0];
    expect(refreshOptions.credentials).toBe("include");
    expect(refreshOptions.headers["X-CSRF-Token"]).toBe("csrf-token-value");
  });

  test("the dashboard shows the profile loaded from GET /auth/me", async () => {
    setCsrfCookie("csrf-token-value");
    // /me returns fresher data than the refresh response did.
    mockApi({
      "POST /api/v1/auth/refresh": () => jsonResponse(200, sessionBody({ ...USER, name: "Stale Name" })),
      "GET /api/v1/auth/me": () => jsonResponse(200, { user: USER }),
    });
    window.history.pushState({}, "", "/account");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getAllByText("@ada_l").length).toBeGreaterThan(0);
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("Member since")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    // No profile picture -> initials avatar.
    expect(screen.getAllByText("AL").length).toBeGreaterThan(0);
  });

  test("an expired session on reload falls back to the logged-out state", async () => {
    setCsrfCookie("stale");
    mockApi({
      "POST /api/v1/auth/refresh": () =>
        jsonResponse(401, { error: { code: "UNAUTHENTICATED", message: "Session expired. Please sign in again." } }),
    });
    window.history.pushState({}, "", "/account");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Log In" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Login / Sign Up" })).toBeInTheDocument();
  });

  test("logout revokes the session on the server and returns the UI to the logged-out state", async () => {
    setCsrfCookie("csrf-token-value");
    const fetchMock = mockApi({
      "POST /api/v1/auth/refresh": () => jsonResponse(200, sessionBody()),
      "GET /api/v1/auth/me": () => jsonResponse(200, { user: USER }),
      "POST /api/v1/auth/logout": () => {
        clearCookies(); // what the server's Set-Cookie does
        return { ok: true, status: 204, json: async () => null };
      },
    });
    window.history.pushState({}, "", "/account");
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Log out/i }));

    expect(await screen.findByRole("heading", { name: "Log In" })).toBeInTheDocument();
    const [, logoutOptions] = callsTo(fetchMock, "POST", "/api/v1/auth/logout")[0];
    expect(logoutOptions.headers["X-CSRF-Token"]).toBe("csrf-token-value");
    expect(logoutOptions.credentials).toBe("include");
    await waitFor(() => expect(screen.getByRole("link", { name: "Login / Sign Up" })).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "User Dashboard" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Account:/ })).not.toBeInTheDocument();
  });

  test("logging out discards the previous user's stored analysis results", async () => {
    setCsrfCookie("csrf-token-value");
    window.sessionStorage.setItem("exoplanet_prediction_session_v1", JSON.stringify({ lightCurveResult: { filename: "mine.csv" } }));
    mockApi({
      "POST /api/v1/auth/refresh": () => jsonResponse(200, sessionBody()),
      "GET /api/v1/auth/me": () => jsonResponse(200, { user: USER }),
      "POST /api/v1/auth/logout": () => {
        clearCookies();
        return { ok: true, status: 204, json: async () => null };
      },
    });
    window.history.pushState({}, "", "/account");
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Log out/i }));
    expect(await screen.findByRole("heading", { name: "Log In" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("exoplanet_prediction_session_v1")).toBeNull();
  });
});
