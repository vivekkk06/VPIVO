import { useCallback, useEffect, useState } from "react";
import { loadEagerBundle, type EagerBundle } from "./services/dataService";
import Dashboard from "./pages/Dashboard";
import DecisionCenter from "./pages/DecisionCenter";
import SessionReplay from "./pages/SessionReplay";
import ProcessExplorer from "./pages/ProcessExplorer";
import Opportunities from "./pages/Opportunities";
import AutomationDemo from "./pages/AutomationDemo";
import ModuleComparison from "./pages/ModuleComparison";
import Day1DataAudit from "./pages/Day1DataAudit";
import Day2Reconstruction from "./pages/Day2Reconstruction";
import Day3ProcessMining from "./pages/Day3ProcessMining";
import Day4EvidenceHealth from "./pages/Day4EvidenceHealth";
import { Notice } from "./components/common";
import { BundleContext } from "./components/BundleContext";
import {
  NAV_GROUPS,
  screenFromHash,
  screensIn,
  type NavParams,
  type NavState,
  type ScreenId,
} from "./navigation";

function focusPageTitle() {
  document.getElementById("page-title")?.focus();
}

export default function App() {
  const [nav, setNav] = useState<NavState>(() => ({
    screen: typeof window === "undefined" ? "dashboard" : screenFromHash(window.location.hash),
    params: {},
    nonce: 0,
  }));
  const [bundle, setBundle] = useState<EagerBundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const navigate = useCallback((screen: ScreenId, params: NavParams = {}) => {
    setNav((prev) => ({ screen, params, nonce: prev.nonce + 1 }));
    setMenuOpen(false);
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

  // After an in-app navigation, move focus to the new page title so keyboard and
  // screen-reader users land on the page they asked for (the initial load keeps focus).
  useEffect(() => {
    if (nav.nonce > 0) focusPageTitle();
  }, [nav.nonce]);

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
  const healthA = bundle?.instrumentation.dataset_a.summary;
  const healthB = bundle?.instrumentation.dataset_b.summary;

  return (
    <div className="layout">
      <button className="skip-link" onClick={focusPageTitle}>Skip to page content</button>

      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">IBY</span>
          <div className="brand-text">
            <p className="brand-name">Operation Log Analysis</p>
            <p className="brand-sub">Evidence-backed automation investigation</p>
          </div>
          <button className="menu-toggle btn small-btn" aria-expanded={menuOpen}
            aria-controls="main-nav" onClick={() => setMenuOpen((open) => !open)}>
            {menuOpen ? "Close menu" : "Menu"}
          </button>
        </div>

        <nav id="main-nav" className={`nav${menuOpen ? " is-open" : ""}`} aria-label="Main">
          {NAV_GROUPS.map((group) => (
            <div className="nav-group" key={group}>
              <p className="nav-group-label" id={`nav-group-${group}`}>{group}</p>
              <ul aria-labelledby={`nav-group-${group}`}>
                {screensIn(group).map((s) => (
                  <li key={s.id}>
                    <button
                      className="navbtn"
                      aria-current={screen === s.id ? "page" : undefined}
                      onClick={() => navigate(s.id)}
                    >
                      <span className="idx" aria-hidden="true">{s.number}</span>
                      <span className="navlabel">{s.label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <dl className={`dataset-status${menuOpen ? " is-open" : ""}`} aria-label="Dataset status">
          <div>
            <dt>Dataset A</dt>
            <dd>{healthA ? healthA.n_sessions : "—"} sessions · ground truth</dd>
          </div>
          <div>
            <dt>Dataset B</dt>
            <dd>{healthB ? healthB.n_sessions : "—"} sessions · no ground truth</dd>
          </div>
          <div>
            <dt>Evidence mode</dt>
            <dd>Read-only</dd>
          </div>
        </dl>
      </aside>

      <main className="main" id="main">
        {error ? (
          <Notice kind="error">
            <strong>Data error.</strong> {error}
          </Notice>
        ) : !bundle ? (
          <p className="muted">Loading analysis bundle…</p>
        ) : (
          <BundleContext.Provider value={bundle}>
            <div className="page" key={screen}>
              {screen === "dashboard" ? (
                <Dashboard bundle={bundle} navigate={navigate} />
              ) : screen === "data-audit" ? (
                <Day1DataAudit bundle={bundle} navigate={navigate} />
              ) : screen === "reconstruction" ? (
                <Day2Reconstruction bundle={bundle} navigate={navigate} />
              ) : screen === "process-mining" ? (
                <Day3ProcessMining bundle={bundle} navigate={navigate} />
              ) : screen === "evidence-health" ? (
                <Day4EvidenceHealth bundle={bundle} navigate={navigate} />
              ) : screen === "decision" ? (
                <DecisionCenter bundle={bundle} navigate={navigate} />
              ) : screen === "replay" ? (
                <SessionReplay bundle={bundle} navParams={params} navNonce={nonce} />
              ) : screen === "processes" ? (
                <ProcessExplorer bundle={bundle} navigate={navigate} navParams={params} navNonce={nonce} />
              ) : screen === "opportunities" ? (
                <Opportunities bundle={bundle} navigate={navigate} />
              ) : screen === "modules" ? (
                <ModuleComparison bundle={bundle} navigate={navigate} />
              ) : (
                <AutomationDemo bundle={bundle} />
              )}
            </div>
          </BundleContext.Provider>
        )}
      </main>
    </div>
  );
}
