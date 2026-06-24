import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/AuthProvider";
import { Button, Card, Field, Input } from "../components/Primitives";
import { AppHeader, PageBody, PageShell } from "../components/Layout";
import styles from "./Auth.module.css";

export function LoginPage() {
  const { token, mode, login, register, setDevToken } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [devTokenInput, setDevTokenInput] = useState("dev-user");

  const dest = (location.state as { from?: string } | null)?.from ?? "/";

  if (token) return <Navigate to={dest} replace />;

  if (mode === "dev") {
    return (
      <PageShell>
        <AppHeader />
        <PageBody>
          <div className={styles.centered}>
            <Card className={styles.card}>
              <h1>Dev sign-in</h1>
              <p className={styles.subtitle}>
                Enter a dev token to use as your identity.
              </p>
              <div className={styles.form}>
                <Field label="Dev token">
                  <Input
                    type="text"
                    value={devTokenInput}
                    onChange={(e) => setDevTokenInput(e.target.value)}
                    autoComplete="off"
                  />
                </Field>
                <Button
                  type="button"
                  onClick={() => {
                    setDevToken(devTokenInput || "dev-user");
                    navigate(dest, { replace: true });
                  }}
                >
                  Enter app
                </Button>
              </div>
            </Card>
          </div>
        </PageBody>
      </PageShell>
    );
  }

  // keycloak mode
  return (
    <PageShell>
      <AppHeader />
      <PageBody>
        <div className={styles.centered}>
          <Card className={styles.card}>
            <h1>Sign in</h1>
            <p className={styles.subtitle}>Open and edit your maps.</p>
            <div className={styles.form}>
              <Button type="button" onClick={() => login()}>
                Sign in with Keycloak
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => register()}
              >
                Create account
              </Button>
            </div>
          </Card>
        </div>
      </PageBody>
    </PageShell>
  );
}
