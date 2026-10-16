import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";

export default function AuthPage() {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const mode = location.pathname === "/register" ? "register" : "login";
  const isRegister = mode === "register";
  const redirectTo = location.state?.from?.pathname || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to={redirectTo} replace />;

  function switchMode(next) {
    setError("");
    navigate(`/${next}`, { replace: true, state: location.state });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    // same rules the API enforces, so the user gets feedback before the round trip
    if (!email.includes("@")) return setError("Enter a valid email");
    if (isRegister && password.length < 8) {
      return setError("Password must be at least 8 characters long");
    }

    setSubmitting(true);
    try {
      if (isRegister) await register(email, password);
      else await login(email, password);
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setError(err.message || "Something went wrong. Try again.");
      setSubmitting(false);
    }
  }

  return (
    <div className="container">
      <h1>Price Watcher</h1>
      <p className="muted">
        Paste a product link and get alerted when the price drops below your target.
      </p>

      <div className="panel">
        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={!isRegister}
            className={!isRegister ? "active" : ""}
            onClick={() => switchMode("login")}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={isRegister}
            className={isRegister ? "active" : ""}
            onClick={() => switchMode("register")}
          >
            Create account
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete={isRegister ? "new-password" : "current-password"}
            placeholder={isRegister ? "At least 8 characters" : "Your password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" disabled={submitting}>
            {submitting
              ? isRegister ? "Creating account…" : "Signing in…"
              : isRegister ? "Create account" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
