import { Link, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../lib/AuthProvider";
import { Button } from "./Primitives";
import styles from "./Layout.module.css";

export function AppHeader({ right }: { right?: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <header className={styles.header}>
      <Link to="/" className={styles.brand}>
        <Logo />
        <span>dungml</span>
      </Link>
      <div className={styles.spacer}>{right}</div>
      <Link to="/docs" className={styles.docsLink} title="DSL reference">
        Docs
      </Link>
      {user ? (
        <div className={styles.userBlock}>
          <span className={styles.userEmail}>{user.email}</span>
          <Button
            variant="ghost"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            Sign out
          </Button>
        </div>
      ) : null}
    </header>
  );
}

function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
      <rect x="3" y="3" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2" />
      <rect x="18" y="3" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2" />
      <rect x="3" y="18" width="26" height="11" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

export function PageShell({ children }: { children: ReactNode }) {
  return <div className={styles.shell}>{children}</div>;
}

export function PageBody({ children }: { children: ReactNode }) {
  return <main className={styles.body}>{children}</main>;
}
