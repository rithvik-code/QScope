import { Component, useMemo, useState, type ErrorInfo, type ReactNode } from "react";
import { Shell, type ModeKey } from "./components/Shell";
import { TransitionPanel } from "./components/motion";
import { Notice } from "./components/ui";
import { StoreProvider, useStore } from "./state/store";
import { ThemeProvider } from "./theme/ThemeProvider";
import { AnalyzeMode } from "./modes/AnalyzeMode";
import { BenchmarkMode } from "./modes/BenchmarkMode";
import { BuildMode } from "./modes/BuildMode";
import { ExecuteMode } from "./modes/ExecuteMode";
import { ExperimentMode } from "./modes/ExperimentMode";
import { MissionControl } from "./modes/MissionControl";
import { NoiseMode } from "./modes/NoiseMode";
import { OptimizeMode } from "./modes/OptimizeMode";
import { ResearchMode } from "./modes/ResearchMode";
import { TraceMode } from "./modes/TraceMode";

/**
 * A fault in one view must not take the whole instrument down: the engine keeps
 * running, the log keeps its entries, and the failure is reported instead of
 * leaving a blank page behind.  React unmounts the subtree on an uncaught error,
 * so this boundary is what makes the rest of the interface survive.
 */
class ModeBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("QScope view failed", error, info.componentStack);
  }

  componentDidUpdate(previous: { resetKey: string }) {
    if (previous.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Notice tone="danger" title="This view failed to render">
        <p className="mono-num text-[11px]">{this.state.error.message}</p>
        <p className="mt-1">
          The API and the stored history are unaffected. Switch to Mission Control and the rest of the environment keeps
          working; the browser console has the full stack.
        </p>
      </Notice>
    );
  }
}

function Workspace() {
  const [mode, setMode] = useState<ModeKey>("control");
  const { errors, meta } = useStore();

  const view = useMemo(() => {
    switch (mode) {
      case "build":
        return <BuildMode onNavigate={setMode} />;
      case "execute":
        return <ExecuteMode onNavigate={setMode} />;
      case "trace":
        return <TraceMode onNavigate={setMode} />;
      case "analyze":
        return <AnalyzeMode onNavigate={setMode} />;
      case "optimize":
        return <OptimizeMode onNavigate={setMode} />;
      case "noise":
        return <NoiseMode onNavigate={setMode} />;
      case "experiment":
        return <ExperimentMode onNavigate={setMode} />;
      case "benchmark":
        return <BenchmarkMode onNavigate={setMode} />;
      case "research":
        return <ResearchMode onNavigate={setMode} />;
      default:
        return <MissionControl onNavigate={setMode} />;
    }
  }, [mode]);

  return (
    <Shell mode={mode} onModeChange={setMode}>
      {errors.boot && (
        <div className="mb-3">
          <Notice tone="danger" title="The API is not answering">
            {errors.boot}. Start it with <span className="mono-num">python -m qscope</span> from the repository root,
            then reload this page.
          </Notice>
        </div>
      )}
      {!meta && !errors.boot && (
        <div className="mb-3">
          <Notice tone="info">Loading the engine catalogue…</Notice>
        </div>
      )}
      <ModeBoundary resetKey={mode}>
        <TransitionPanel activeKey={mode}>{view}</TransitionPanel>
      </ModeBoundary>
    </Shell>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <StoreProvider>
        <Workspace />
      </StoreProvider>
    </ThemeProvider>
  );
}
