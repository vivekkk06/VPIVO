import { useCallback, useEffect, useState } from "react";
import { loadEagerBundle, type EagerBundle } from "./services/dataService";
import Dashboard from "./pages/Dashboard";
import DecisionCenter from "./pages/DecisionCenter";
import SessionReplay from "./pages/SessionReplay";
import ProcessExplorer from "./pages/ProcessExplorer";
import Opportunities from "./pages/Opportunities";
import AutomationDemo from "./pages/AutomationDemo";
import { Notice } from "./components/common";
import {
  SCREENS,
  screenFromHash,
  type NavParams,
  type NavState,
  type ScreenId,
} from "./navigation";

export default function App() {
  const [nav, setNav] = useState<NavState>(() => ({
    screen: typeof window === "undefined" ? "dashboard" : screenFromHash(window.location.hash),
    params: {},
    nonce: 0,
  }));
  const [bundle, setBundle] = useState<EagerBundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  const navigate = useCallback((screen: ScreenId, params: NavParams = {}) => {
    setNav((prev) => ({ screen, params, nonce: prev.nonce + 1 }));
    if (typeof window !== "undefined" && window.location.hash !== `#${screen}`) {
      window.location.hash = screen;
    }
  }, []);

  // Keep the browser back/forward buttons working without a router.
  useEffect(() => {
    const onHashChange = () => {
      const screen = screenFromHash(window.location.hash);
      setNav((prev) => (prev.screen === screen ? prev : { screen, params: {}, nonce: prev.nonce + 1 }));
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadEagerBundle()
      .then((b) => {
        if (!cancelled) setBundle(b);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const { screen, params, nonce } = nav;

  return (
    <div className="layout">
      <nav className="sidebar" aria-label="Main">
        <h1>IBY — Operation Log Analysis</h1>
        <p className="sub">Days 1–4 evidence, read-only</p>
        {SCREENS.map((s, i) => (
          <button
            key={s.id}
            className="navbtn"
            aria-current={screen === s.id ? "page" : undefined}
            onClick={() => navigate(s.id)}
          >
            <span className="idx">{i + 1}</span>
            {s.label}
          </button>
        ))}
        <p className="pipeline" aria-label="Analysis pipeline">
          Raw logs → Instrumentation → Segmentation → Executions → Process discovery →
          Opportunity ranking → Evidence → Safe automation
        </p>
      </nav>

      <main className="main">
        {error ? (
          <Notice kind="error">
            <strong>Data error.</strong> {error}
          </Notice>
        ) : !bundle ? (
          <p className="muted">Loading analysis bundle…</p>
        ) : screen === "dashboard" ? (
          <Dashboard bundle={bundle} navigate={navigate} />
        ) : screen === "decision" ? (
          <DecisionCenter bundle={bundle} navigate={navigate} />
        ) : screen === "replay" ? (
          <SessionReplay bundle={bundle} navParams={params} navNonce={nonce} />
        ) : screen === "processes" ? (
          <ProcessExplorer bundle={bundle} navigate={navigate} navParams={params} navNonce={nonce} />
        ) : screen === "opportunities" ? (
          <Opportunities bundle={bundle} navigate={navigate} />
        ) : (
          <AutomationDemo bundle={bundle} />
        )}
      </main>
    </div>
  );
}
