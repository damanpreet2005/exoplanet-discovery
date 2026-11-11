/**
 * Server-side validation and normalization of account input. The frontend
 * mirrors these rules for instant feedback, but this module is the authority:
 * nothing reaches the database without passing through it.
 *
 * Error messages never echo the submitted value (so a password can never end
 * up in a response or a log line via a validation message).
 */
const { FieldValidationError } = require("../errors");

const NAME_MAX = 100;
const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{1,28}[a-z0-9]$/;
const EMAIL_MAX = 254;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PASSWORD_MIN = 10;
// Upper bound keeps hashing cost bounded (Argon2 hashes any length, but an
// unbounded input is a cheap way to burn CPU).
const PASSWORD_MAX = 128;
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS_RE = /[\u0000-\u001f\u007f]/;

// A short deny-list of the most common passwords that would otherwise pass
// the length/character rules.
const COMMON_PASSWORDS = new Set([
  "password123",
  "password1234",
  "1234567890a",
  "qwerty12345",
  "qwertyuiop1",
  "iloveyou123",
  "letmein1234",
  "welcome1234",
  "abc1234567",
  "admin12345",
  "passw0rd123",
  "exoplanet123",
]);

function normalizeName(value) {
  if (typeof value !== "string") return null;
  return value.normalize("NFC").replace(/\s+/g, " ").trim();
}

function normalizeUsername(value) {
  if (typeof value !== "string") return null;
  return value.normalize("NFKC").trim().toLowerCase();
}

function normalizeEmail(value) {
  if (typeof value !== "string") return null;
  return value.normalize("NFKC").trim().toLowerCase();
}

function passwordProblem(password, { username, email } = {}) {
  if (typeof password !== "string" || password.length === 0) return "Password is required.";
  if (password.length < PASSWORD_MIN) return `Password must be at least ${PASSWORD_MIN} characters.`;
  if (password.length > PASSWORD_MAX) return `Password must be at most ${PASSWORD_MAX} characters.`;
  if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
    return "Password must contain at least one letter and one number.";
  }
  const lowered = password.toLowerCase();
  if (COMMON_PASSWORDS.has(lowered)) return "This password is too common. Choose a less predictable one.";
  if (username && username.length >= 3 && lowered.includes(username)) {
    return "Password must not contain your username.";
  }
  const local = email ? email.split("@")[0] : "";
  if (local && local.length >= 3 && lowered.includes(local)) {
    return "Password must not contain your email address.";
  }
  return null;
}

/** Validates a sign-up body; returns normalized values or throws FieldValidationError. */
function validateRegistration(body) {
  const input = body && typeof body === "object" ? body : {};
  const fields = {};

  const name = normalizeName(input.name);
  if (!name) fields.name = "Full name is required.";
  else if (name.length > NAME_MAX) fields.name = `Full name must be at most ${NAME_MAX} characters.`;
  else if (CONTROL_CHARS_RE.test(name)) fields.name = "Full name contains invalid characters.";

  const username = normalizeUsername(input.username);
  if (!username) fields.username = "Username is required.";
  else if (!USERNAME_RE.test(username)) {
    fields.username =
      "Username must be 3-30 characters: letters, numbers, dots, hyphens or underscores, starting and ending with a letter or number.";
  }

  const email = normalizeEmail(input.email);
  if (!email) fields.email = "Email address is required.";
  else if (email.length > EMAIL_MAX || !EMAIL_RE.test(email) || email.split("@")[0].length > 64) {
    fields.email = "Enter a valid email address.";
  }

  const passwordIssue = passwordProblem(input.password, {
    username: fields.username ? null : username,
    email: fields.email ? null : email,
  });
  if (passwordIssue) fields.password = passwordIssue;

  if (input.confirm_password !== undefined && input.confirm_password !== input.password) {
    fields.confirm_password = "Passwords do not match.";
  }

  if (Object.keys(fields).length > 0) throw new FieldValidationError(fields);
  return { name, username, email, password: input.password };
}

/** Validates a login body. Strength rules are deliberately NOT applied here. */
function validateLogin(body) {
  const input = body && typeof body === "object" ? body : {};
  const fields = {};
  const identifier = typeof input.identifier === "string" ? input.identifier.normalize("NFKC").trim().toLowerCase() : "";
  if (!identifier) fields.identifier = "Email or username is required.";
  else if (identifier.length > EMAIL_MAX) fields.identifier = "Email or username is too long.";
  if (typeof input.password !== "string" || input.password.length === 0) fields.password = "Password is required.";
  else if (input.password.length > PASSWORD_MAX) fields.password = "Password is too long.";
  if (Object.keys(fields).length > 0) throw new FieldValidationError(fields);
  return { identifier, password: input.password, isEmail: identifier.includes("@") };
}

module.exports = {
  validateRegistration,
  validateLogin,
  normalizeEmail,
  normalizeUsername,
  passwordProblem,
  PASSWORD_MIN,
  PASSWORD_MAX,
};
