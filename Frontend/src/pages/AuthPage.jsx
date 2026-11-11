import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import Icon from "../components/Icon";
import { useAuth } from "../context/AuthContext";
import { PASSWORD_RULES, mapServerFields, validateLogin, validateSignUp } from "../lib/accountValidation";

const EMPTY_SIGNUP = { name: "", username: "", email: "", password: "", confirmPassword: "" };
const EMPTY_LOGIN = { identifier: "", password: "" };

function Field({ id, label, error, hint, ...inputProps }) {
  const describedBy = [error ? `${id}-error` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="auth-field">
      <label htmlFor={id} className="auth-label">
        {label}
      </label>
      <input
        id={id}
        className={`param-input${error ? " is-invalid" : ""}`}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={describedBy}
        {...inputProps}
      />
      {hint}
      {error && (
        <p id={`${id}-error`} className="auth-field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function PasswordChecklist({ password }) {
  return (
    <ul id="signup-password-hint" className="auth-checklist" aria-label="Password requirements">
      {PASSWORD_RULES.map((rule) => {
        const ok = rule.test(password);
        return (
          <li key={rule.id} className={ok ? "ok" : undefined}>
            <Icon name={ok ? "check_circle" : "radio_button_unchecked"} size={16} />
            {rule.label}
          </li>
        );
      })}
    </ul>
  );
}

function LoginForm({ onSuccess }) {
  const { login } = useAuth();
  const [values, setValues] = useState(EMPTY_LOGIN);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const update = (field) => (event) => setValues((prev) => ({ ...prev, [field]: event.target.value }));

  async function handleSubmit(event) {
    event.preventDefault();
    setFormError(null);
    const nextErrors = validateLogin(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    setSubmitting(true);
    try {
      await login({ identifier: values.identifier.trim(), password: values.password });
      onSuccess();
    } catch (err) {
      setErrors(mapServerFields(err.fields));
      setFormError(err.message);
      setValues((prev) => ({ ...prev, password: "" }));
      setSubmitting(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit} noValidate aria-label="Log in">
      {formError && (
        <div className="auth-form-error" role="alert">
          <Icon name="error" size={18} />
          {formError}
        </div>
      )}
      <Field
        id="login-identifier"
        label="Email or username"
        type="text"
        autoComplete="username"
        autoCapitalize="none"
        spellCheck="false"
        value={values.identifier}
        onChange={update("identifier")}
        error={errors.identifier}
        required
      />
      <Field
        id="login-password"
        label="Password"
        type="password"
        autoComplete="current-password"
        value={values.password}
        onChange={update("password")}
        error={errors.password}
        required
      />
      <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
        {submitting ? (
          <>
            <Icon name="progress_activity" size={18} className="icon-spin" /> Signing in…
          </>
        ) : (
          <>
            <Icon name="login" size={18} /> Log in
          </>
        )}
      </button>
    </form>
  );
}

function SignUpForm({ onSuccess }) {
  const { register } = useAuth();
  const [values, setValues] = useState(EMPTY_SIGNUP);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const update = (field) => (event) => setValues((prev) => ({ ...prev, [field]: event.target.value }));

  async function handleSubmit(event) {
    event.preventDefault();
    setFormError(null);
    const nextErrors = validateSignUp(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    setSubmitting(true);
    try {
      await register({
        name: values.name.trim(),
        username: values.username.trim(),
        email: values.email.trim(),
        password: values.password,
        confirmPassword: values.confirmPassword,
      });
      onSuccess();
    } catch (err) {
      const fieldErrors = mapServerFields(err.fields);
      setErrors(fieldErrors);
      setFormError(Object.keys(fieldErrors).length > 0 ? "Please fix the highlighted fields." : err.message);
      setSubmitting(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit} noValidate aria-label="Sign up">
      {formError && (
        <div className="auth-form-error" role="alert">
          <Icon name="error" size={18} />
          {formError}
        </div>
      )}
      <Field
        id="signup-name"
        label="Full name"
        type="text"
        autoComplete="name"
        value={values.name}
        onChange={update("name")}
        error={errors.name}
        maxLength={100}
        required
      />
      <Field
        id="signup-username"
        label="Username"
        type="text"
        autoComplete="username"
        autoCapitalize="none"
        spellCheck="false"
        value={values.username}
        onChange={update("username")}
        error={errors.username}
        maxLength={30}
        required
      />
      <Field
        id="signup-email"
        label="Email address"
        type="email"
        autoComplete="email"
        value={values.email}
        onChange={update("email")}
        error={errors.email}
        maxLength={254}
        required
      />
      <Field
        id="signup-password"
        label="Password"
        type="password"
        autoComplete="new-password"
        value={values.password}
        onChange={update("password")}
        error={errors.password}
        hint={<PasswordChecklist password={values.password} />}
        required
      />
      <Field
        id="signup-confirm-password"
        label="Confirm password"
        type="password"
        autoComplete="new-password"
        value={values.confirmPassword}
        onChange={update("confirmPassword")}
        error={errors.confirmPassword}
        required
      />
      <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
        {submitting ? (
          <>
            <Icon name="progress_activity" size={18} className="icon-spin" /> Creating account…
          </>
        ) : (
          <>
            <Icon name="person_add" size={18} /> Create account
          </>
        )}
      </button>
      <p className="auth-footnote">You'll be signed in automatically once your account is created.</p>
    </form>
  );
}

/** Login and sign-up on one page; `mode` comes from the route (/login or /signup). */
export default function AuthPage({ mode }) {
  const { status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const destination = location.state?.from || "/account";

  if (status === "authenticated") return <Navigate to={destination} replace />;

  const isLogin = mode === "login";
  const goToDestination = () => navigate(destination, { replace: true });

  return (
    <div className="fade-in auth-page">
      <header className="page-header">
        <h1 className="page-title">{isLogin ? "Log In" : "Create Account"}</h1>
        <p className="page-subtitle">
          {isLogin
            ? "Sign in to your Exo Discovery account to upload light curves and run the analysis."
            : "Create an Exo Discovery account to upload light curves and run the analysis."}
        </p>
      </header>

      <div className="panel auth-card">
        <div className="auth-tabs" role="tablist" aria-label="Account access">
          <Link
            to="/login"
            state={location.state}
            replace
            role="tab"
            aria-selected={isLogin}
            className={`auth-tab${isLogin ? " active" : ""}`}
          >
            Log in
          </Link>
          <Link
            to="/signup"
            state={location.state}
            replace
            role="tab"
            aria-selected={!isLogin}
            className={`auth-tab${!isLogin ? " active" : ""}`}
          >
            Sign up
          </Link>
        </div>

        {isLogin ? <LoginForm onSuccess={goToDestination} /> : <SignUpForm onSuccess={goToDestination} />}

        <p className="auth-switch">
          {isLogin ? "New to Exo Discovery? " : "Already have an account? "}
          <Link to={isLogin ? "/signup" : "/login"} state={location.state} replace>
            {isLogin ? "Create an account" : "Log in instead"}
          </Link>
        </p>
      </div>
    </div>
  );
}
