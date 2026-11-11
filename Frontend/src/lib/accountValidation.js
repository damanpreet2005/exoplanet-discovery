/**
 * Instant-feedback mirror of the backend's account rules
 * (Backend/src/auth/validation.js). The backend remains the authority and
 * re-validates everything; keep the two in step when changing a rule.
 */
export const PASSWORD_MIN = 10;
export const PASSWORD_MAX = 128;
const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{1,28}[a-z0-9]$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const PASSWORD_RULES = [
  { id: "length", label: `At least ${PASSWORD_MIN} characters`, test: (p) => p.length >= PASSWORD_MIN && p.length <= PASSWORD_MAX },
  { id: "letter", label: "Contains a letter", test: (p) => /[A-Za-z]/.test(p) },
  { id: "number", label: "Contains a number", test: (p) => /[0-9]/.test(p) },
];

export function validateSignUp({ name, username, email, password, confirmPassword }) {
  const errors = {};
  const cleanName = name.trim();
  const cleanUsername = username.trim().toLowerCase();
  const cleanEmail = email.trim().toLowerCase();

  if (!cleanName) errors.name = "Full name is required.";
  else if (cleanName.length > 100) errors.name = "Full name must be at most 100 characters.";

  if (!cleanUsername) errors.username = "Username is required.";
  else if (!USERNAME_RE.test(cleanUsername)) {
    errors.username = "3-30 characters: letters, numbers, dots, hyphens or underscores, starting and ending with a letter or number.";
  }

  if (!cleanEmail) errors.email = "Email address is required.";
  else if (cleanEmail.length > 254 || !EMAIL_RE.test(cleanEmail)) errors.email = "Enter a valid email address.";

  if (!password) errors.password = "Password is required.";
  else {
    const failed = PASSWORD_RULES.find((rule) => !rule.test(password));
    if (failed) errors.password = password.length > PASSWORD_MAX ? `Password must be at most ${PASSWORD_MAX} characters.` : `Password must meet every requirement: ${failed.label.toLowerCase()}.`;
    else if (cleanUsername.length >= 3 && password.toLowerCase().includes(cleanUsername)) {
      errors.password = "Password must not contain your username.";
    }
  }

  if (!confirmPassword) errors.confirmPassword = "Please confirm your password.";
  else if (confirmPassword !== password) errors.confirmPassword = "Passwords do not match.";

  return errors;
}

export function validateLogin({ identifier, password }) {
  const errors = {};
  if (!identifier.trim()) errors.identifier = "Enter your email address or username.";
  if (!password) errors.password = "Enter your password.";
  return errors;
}

/** Maps backend field names (snake_case) to this form's field names. */
export function mapServerFields(fields) {
  if (!fields) return {};
  const out = { ...fields };
  if (out.confirm_password) {
    out.confirmPassword = out.confirm_password;
    delete out.confirm_password;
  }
  return out;
}
