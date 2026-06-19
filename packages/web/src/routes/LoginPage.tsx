import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/AuthProvider";
import { ApiError } from "../lib/api";
import { Button, Card, Field, Input } from "../components/Primitives";
import { AppHeader, PageBody, PageShell } from "../components/Layout";
import styles from "./Auth.module.css";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      const dest =
        (location.state as { from?: string } | null)?.from ?? "/";
      navigate(dest, { replace: true });
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not sign in. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <PageShell>
      <AppHeader />
      <PageBody>
        <div className={styles.centered}>
          <Card className={styles.card}>
            <h1>Sign in</h1>
            <p className={styles.subtitle}>
              Open and edit your maps.
            </p>
            <form onSubmit={onSubmit} className={styles.form}>
              <Field label="Email">
                <Input
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
              <Field label="Password">
                <Input
                  type="password"
                  autoComplete="current-password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
              {error ? <div className={styles.formError}>{error}</div> : null}
              <Button type="submit" disabled={submitting}>
                {submitting ? "Signing in…" : "Sign in"}
              </Button>
            </form>
            <p className={styles.alt}>
              No account? <Link to="/register">Create one.</Link>
            </p>
          </Card>
        </div>
      </PageBody>
    </PageShell>
  );
}
