import { useMemo, useState } from "react";
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
      <TransitionPanel activeKey={mode}>{view}</TransitionPanel>
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
