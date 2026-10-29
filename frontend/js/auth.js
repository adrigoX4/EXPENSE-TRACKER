const body = document.body;
const mode = body.dataset.authMode === "signup" ? "signup" : "login";
const authEndpoint = mode === "signup" ? "/api/auth/register" : "/api/auth/login";

const form = document.getElementById("auth-form");
const emailInput = document.getElementById("auth-email");
const passwordInput = document.getElementById("auth-password");
const confirmField = document.getElementById("auth-confirm-field");
const confirmInput = document.getElementById("auth-confirm");
const submitButton = document.getElementById("auth-submit");
const submitLabel = document.getElementById("auth-submit-label");
const errorBox = document.getElementById("auth-error");
const revealButton = document.getElementById("auth-reveal");
const passwordHint = document.getElementById("auth-password-hint");
const firstRunNote = document.getElementById("auth-first-run");
const signupClosedNote = document.getElementById("auth-signup-closed");
const altLink = document.getElementById("auth-alt-link");
const altHref = altLink?.getAttribute("href") || "/login";

form.action = authEndpoint;

if (mode === "signup") {
  confirmField.hidden = false;
  confirmInput.required = true;
  passwordInput.autocomplete = "new-password";
  passwordHint.hidden = false;
  submitLabel.textContent = "Create account";
} else {
  submitLabel.textContent = "Sign in";
}

function safeNext() {
  const raw = new URLSearchParams(window.location.search).get("next") || "";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/dashboard";
  if (raw.startsWith("/login") || raw.startsWith("/signup")) return "/dashboard";
  return raw;
}

function showError(message, field) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  if (field) field.focus();
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function setBusy(busy) {
  submitButton.disabled = busy;
  submitButton.setAttribute("aria-busy", String(busy));
  submitLabel.textContent = busy
    ? mode === "signup"
      ? "Creating account…"
      : "Signing in…"
    : mode === "signup"
      ? "Create account"
      : "Sign in";
}

revealButton?.addEventListener("click", () => {
  const reveal = passwordInput.type === "password";
  passwordInput.type = reveal ? "text" : "password";
  revealButton.textContent = reveal ? "Hide" : "Show";
  revealButton.setAttribute("aria-pressed", String(reveal));
  passwordInput.focus();
});

async function loadStatus() {
  try {
    const response = await fetch("/api/auth/status", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return;
    const status = await response.json();
    if (status.authenticated) {
      window.location.replace(safeNext());
      return;
    }
    if (!status.has_accounts) {
      firstRunNote.hidden = false;
      if (mode === "login") {
        window.location.replace("/signup");
        return;
      }
    }
    if (mode === "signup" && !status.allow_signup) {
      signupClosedNote.hidden = false;
      form.querySelectorAll("input, button").forEach((node) => {
        node.disabled = true;
      });
      altLink.setAttribute("href", "/login");
      altLink.textContent = "Sign in with an existing account";
    }
  } catch {
    /* the form still works when the status probe fails */
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();

  const email = emailInput.value.trim().toLowerCase();
  const password = passwordInput.value;

  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    showError("Enter a valid email address, for example name@example.com.", emailInput);
    return;
  }
  if (!password) {
    showError("Enter your password.", passwordInput);
    return;
  }
  if (mode === "signup") {
    if (password.length < 8) {
      showError("Password must be at least 8 characters.", passwordInput);
      return;
    }
    if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      showError("Password must include at least one letter and one number.", passwordInput);
      return;
    }
    if (confirmInput.value !== password) {
      showError("Both passwords must match.", confirmInput);
      return;
    }
  }

  setBusy(true);
  try {
    const response = await fetch(authEndpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    let data = null;
    try {
      data = await response.json();
    } catch {
      /* non-JSON response */
    }
    if (response.ok) {
      window.location.replace(safeNext());
      return;
    }
    const error = data?.error || data?.detail;
    const message =
      typeof error === "string"
        ? error
        : error?.message || `The server responded with ${response.status}.`;
    if (response.status === 409 && mode === "signup") {
      altLink.setAttribute("href", `/login?next=${encodeURIComponent(safeNext())}`);
      altLink.textContent = "Sign in to the existing account";
      showError(message, emailInput);
    } else if (response.status === 401) {
      showError(message, passwordInput);
    } else if (response.status === 403) {
      showError(message);
    } else {
      showError(message);
    }
  } catch {
    showError("Cannot reach the server. Check your connection and try again.");
  } finally {
    setBusy(false);
  }
});

if (!["/login", "/signup"].includes(altHref)) {
  altLink.setAttribute("href", "/login");
}

loadStatus();
