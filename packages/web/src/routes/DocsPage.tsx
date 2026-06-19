import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import * as api from "../lib/api";
import { AppHeader, PageBody, PageShell } from "../components/Layout";
import { Markdown } from "../components/Markdown";
import styles from "./Docs.module.css";

const DEFAULT_DOC = "dsl";

export function DocsPage() {
  const { docId = DEFAULT_DOC } = useParams();

  const { data: source, isLoading, error } = useQuery({
    queryKey: ["docs", docId],
    queryFn: () => api.docs.get(docId),
  });

  return (
    <PageShell>
      <AppHeader right={<h1 className={styles.headerTitle}>Docs</h1>} />
      <PageBody>
        <article className={styles.article}>
          {isLoading ? (
            <div className={styles.muted}>Loading…</div>
          ) : error ? (
            <div className={styles.muted}>
              Couldn't load that doc. {String((error as Error).message)}
            </div>
          ) : (
            <Markdown source={source ?? ""} />
          )}
        </article>
      </PageBody>
    </PageShell>
  );
}
