/**
 * Application state.
 *
 * One working circuit, one settings block, and the artefacts each mode produces.
 * Every artefact is whatever the API returned, unmodified — the interface never
 * recomputes a metric, and the run log records what was asked for so an
 * experiment can be described later without guessing.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  api,
  ApiError,
  downloadBlob,
  streamExperiment as openExperimentStream,
  streamTrace as openTraceStream,
  type AIAnswer,
  type Backend,
  type BenchmarkPayload,
  type CircuitDocument,
  type CircuitOperation,
  type CircuitSource,
  type Comparison,
  type ExperimentOutcome,
  type HardwareReport,
  type Meta,
  type Mode,
  type NoiseSpec,
  type OptimizationResult,
  type OptimizerLevel,
  type Plan,
  type ReportPayload,
  type SimulationResult,
  type StateMetrics,
  type StoredExperiment,
  type TraceResponse,
  type TraceStep,
  type WhatIf,
} from "../lib/api";

export interface Settings {
  shots: number;
  seed: number;
  backend: Backend;
  noise: NoiseSpec;
  noiseStrength: number;
  traceDepth: "fast" | "standard" | "full";
  termLimit: number;
  optimizerLevel: OptimizerLevel;
  verify: boolean;
  compareIdeal: boolean;
  memoryBudgetMb: number | null;
  store: boolean;
}

export interface LogEntry {
  at: string;
  action: string;
  detail: string;
  seconds?: number;
  ok: boolean;
}

const DEFAULT_SETTINGS: Settings = {
  shots: 2048,
  seed: 11,
  backend: "auto",
  noise: { name: "ideal" },
  noiseStrength: 0,
  traceDepth: "standard",
  termLimit: 24,
  optimizerLevel: "standard",
  verify: true,
  compareIdeal: true,
  memoryBudgetMb: null,
  store: true,
};

interface StoreValue {
  meta: Meta | null;
  health: Awaited<ReturnType<typeof api.health>> | null;
  loading: Record<string, boolean>;
  errors: Record<string, string>;
  settings: Settings;
  setSettings: (patch: Partial<Settings>) => void;
  selection: CircuitSource;
  document: CircuitDocument | null;
  plan: Plan | null;
  result: SimulationResult | null;
  experimentId: string | null;
  trace: TraceResponse | null;
  liveStep: { step: TraceStep; index: number } | null;
  optimization: OptimizationResult | null;
  compareResult: Comparison | null;
  whatIf: WhatIf | null;
  hardware: HardwareReport | null;
  evolution: Awaited<ReturnType<typeof api.evolve>> | null;
  experiment: ExperimentOutcome | null;
  experimentProgress: { index: number; total: number; label: string } | null;
  benchmark: BenchmarkPayload | null;
  answer: AIAnswer | null;
  report: ReportPayload | null;
  history: StoredExperiment[];
  log: LogEntry[];

  setSource: (source: CircuitSource) => Promise<void>;
  loadAlgorithm: (key: string, kwargs?: Record<string, unknown>) => Promise<void>;
  loadQasm: (qasm: string) => Promise<void>;
  resetCircuit: (numQubits: number, numClbits?: number) => Promise<void>;
  editCircuit: (mutate: (operations: CircuitOperation[]) => CircuitOperation[], name?: string) => Promise<void>;
  setQubitCount: (count: number) => Promise<void>;
  runPanic: (label: string, task: () => Promise<void>) => Promise<void>;
  run: (key: string, task: () => Promise<void>) => Promise<void>;

  planRun: () => Promise<void>;
  simulate: () => Promise<void>;
  traceCircuit: (maxSteps?: number | null) => Promise<void>;
  streamTrace: (options: { delayMs: number; maxSteps?: number | null }) => { close: () => void };
  optimize: () => Promise<void>;
  compare: (other: CircuitSource) => Promise<void>;
  runWhatIf: (modification: Record<string, unknown>) => Promise<void>;
  analyseHardware: (device: string, route: boolean) => Promise<void>;
  evolve: (generations: number, population: number) => Promise<void>;
  runExperiment: (request: Record<string, unknown>) => Promise<void>;
  /** Runs a sweep over the websocket, reporting progress point by point. */
  streamExperiment: (request: Record<string, unknown>) => { close: () => void };
  exportReport: (request: Parameters<typeof api.report>[0], format: string) => Promise<void>;
  runBenchmark: (request: Record<string, unknown>) => Promise<void>;
  ask: (body: Record<string, unknown>) => Promise<void>;
  buildReport: (kind: string, payload: Record<string, unknown>, title?: string, objective?: string) => Promise<void>;
  refreshHistory: (params?: Record<string, string | number | undefined>) => Promise<void>;
  deleteStored: (id: string) => Promise<void>;
  reproduce: (id: string) => Promise<Awaited<ReturnType<typeof api.historyReproduce>> | null>;
  note: (action: string, detail: string, ok?: boolean) => void;
}

const StoreContext = createContext<StoreValue | null>(null);

const DEFAULT_SOURCE: CircuitSource = { algorithm: "bell_state" };

export function StoreProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.health>> | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [settings, setSettingsState] = useState<Settings>(DEFAULT_SETTINGS);
  const [selection, setSelection] = useState<CircuitSource>(DEFAULT_SOURCE);
  const [document, setDocument] = useState<CircuitDocument | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [experimentId, setExperimentId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TraceResponse | null>(null);
  const [liveStep, setLiveStep] = useState<{ step: TraceStep; index: number } | null>(null);
  const [optimization, setOptimization] = useState<OptimizationResult | null>(null);
  const [compareResult, setCompareResult] = useState<Comparison | null>(null);
  const [whatIf, setWhatIf] = useState<WhatIf | null>(null);
  const [hardware, setHardware] = useState<HardwareReport | null>(null);
  const [evolution, setEvolution] = useState<StoreValue["evolution"]>(null);
  const [experiment, setExperiment] = useState<ExperimentOutcome | null>(null);
  const [experimentProgress, setExperimentProgress] = useState<StoreValue["experimentProgress"]>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkPayload | null>(null);
  const [answer, setAnswer] = useState<AIAnswer | null>(null);
  const [report, setReport] = useState<ReportPayload | null>(null);
  const [history, setHistory] = useState<StoredExperiment[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const selectionRef = useRef(selection);
  selectionRef.current = selection;

  const note = useCallback((action: string, detail: string, ok = true, seconds?: number) => {
    setLog((entries) => [
      { at: new Date().toLocaleTimeString(), action, detail, ok, seconds },
      ...entries,
    ].slice(0, 120));
  }, []);

  const run = useCallback(
    async (key: string, task: () => Promise<void>) => {
      setLoading((state) => ({ ...state, [key]: true }));
      setErrors((state) => ({ ...state, [key]: "" }));
      try {
        await task();
      } catch (error) {
        const message =
          error instanceof ApiError && error.hint ? `${error.message} — ${error.hint}` : (error as Error).message;
        setErrors((state) => ({ ...state, [key]: message }));
        note(key, message, false);
      } finally {
        setLoading((state) => ({ ...state, [key]: false }));
      }
    },
    [note],
  );

  const setSettings = useCallback((patch: Partial<Settings>) => {
    setSettingsState((current) => ({ ...current, ...patch }));
  }, []);

  const setSource = useCallback(
    async (source: CircuitSource) => {
      setSelection(source);
      const document = await api.document(source);
      setDocument(document);
      setPlan(null);
    },
    [],
  );

  useEffect(() => {
    void (async () => {
      try {
        const [metaPayload, healthPayload] = await Promise.all([api.meta(), api.health()]);
        setMeta(metaPayload);
        setHealth(healthPayload);
        await setSource(DEFAULT_SOURCE);
        const historyPayload = await api.history({ limit: 20 });
        setHistory(historyPayload.experiments);
      } catch (error) {
        setErrors((state) => ({ ...state, boot: (error as Error).message }));
      }
    })();
  }, [setSource]);

  const resolvedNoise = useCallback((): NoiseSpec => {
    if (settings.noiseStrength > 0) {
      const base = settings.noise.name && settings.noise.name !== "ideal" ? settings.noise : { name: "depolarizing", params: { p: 0.05 } };
      return { ...base, scale: settings.noiseStrength };
    }
    return settings.noise;
  }, [settings.noise, settings.noiseStrength]);

  const value = useMemo<StoreValue>(() => {
    const runFor = (key: string, task: () => Promise<void>) => run(key, task);
    return {
      meta,
      health,
      loading,
      errors,
      settings,
      setSettings,
      selection,
      document,
      plan,
      result,
      experimentId,
      trace,
      liveStep,
      optimization,
      compareResult,
      whatIf,
      hardware,
      evolution,
      experiment,
      experimentProgress,
      answer,
      report,
      history,
      log,
      setSource,
      runPanic: runFor,
      run: runFor,
      note,

      loadAlgorithm: async (key, kwargs = {}) => {
        await runFor("load", async () => {
          const source: CircuitSource = { algorithm: key, algorithm_kwargs: kwargs };
          await setSource(source);
          note("load algorithm", `${key}${Object.keys(kwargs).length ? `(${JSON.stringify(kwargs)})` : ""}`);
        });
      },
      loadQasm: async (qasm) => {
        await runFor("load", async () => {
          const loaded = await api.fromQasm(qasm);
          setSelection({ circuit: loaded });
          setDocument(loaded);
          note("import QASM", `${loaded.num_qubits} qubits, ${loaded.operations.length} operations`);
        });
      },
      resetCircuit: async (numQubits, numClbits = numQubits) => {
        await runFor("load", async () => {
          const source: CircuitSource = { num_qubits: numQubits, num_clbits: numClbits, name: "circuit" };
          await setSource(source);
          note("new circuit", `${numQubits} qubits`);
        });
      },
      editCircuit: async (mutate, name) => {
        const base = document;
        if (!base) return;
        await runFor("edit", async () => {
          const operations = mutate([...base.operations]);
          const payload = {
            format: base.format,
            version: base.version,
            name: name ?? base.name,
            num_qubits: base.num_qubits,
            num_clbits: base.num_clbits,
            operations,
            metadata: base.metadata,
          };
          const updated = await api.document({ circuit: payload });
          setSelection({ circuit: updated });
          setDocument(updated);
          setPlan(null);
        });
      },
      setQubitCount: async (count) => {
        const base = document;
        if (!base || count < 1) return;
        await runFor("edit", async () => {
          const keep = base.operations.filter((operation) =>
            [...operation.controls, ...operation.targets].every((wire) => wire < count),
          );
          const dropped = base.operations.length - keep.length;
          const payload = {
            format: base.format,
            version: base.version,
            name: base.name,
            num_qubits: count,
            num_clbits: Math.min(base.num_clbits || count, count),
            operations: keep,
          };
          const updated = await api.document({ circuit: payload });
          setSelection({ circuit: updated });
          setDocument(updated);
          note(
            "resize register",
            `${base.num_qubits} → ${count} qubits${dropped ? `, ${dropped} operation(s) on removed wires dropped` : ""}`,
          );
        });
      },

      planRun: async () => {
        await runFor("plan", async () => {
          const started = performance.now();
          const payload = await api.plan({
            source: selectionRef.current,
            backend: settings.backend,
            shots: settings.shots,
            noise: resolvedNoise(),
            memory_budget_mb: settings.memoryBudgetMb,
          });
          setPlan(payload);
          setDocument(payload.circuit);
          note("plan", `${payload.backend} · ${payload.representation}`, !payload.blocked, (performance.now() - started) / 1000);
        });
      },

      simulate: async () => {
        await runFor("simulate", async () => {
          const started = performance.now();
          const payload = await api.simulate({
            source: selectionRef.current,
            backend: settings.backend,
            shots: settings.shots,
            seed: settings.seed,
            noise: resolvedNoise(),
            compare_ideal: settings.compareIdeal,
            memory_budget_mb: settings.memoryBudgetMb,
            store: settings.store,
            label: document?.name,
          });
          setResult(payload.result);
          setDocument(payload.circuit);
          setPlan(payload.plan);
          setExperimentId(payload.experiment_id);
          note(
            "execute",
            `${payload.result.mode} · ${payload.result.backend} · ${payload.result.shots} shots`,
            true,
            (performance.now() - started) / 1000,
          );
          if (payload.experiment_id) void api.history({ limit: 20 }).then((page) => setHistory(page.experiments));
        });
      },

      traceCircuit: async (maxSteps) => {
        await runFor("trace", async () => {
          const started = performance.now();
          const payload = await api.trace({
            source: selectionRef.current,
            depth: settings.traceDepth,
            term_limit: settings.termLimit,
            max_steps: maxSteps ?? null,
          });
          setTrace(payload);
          setLiveStep(null);
          note("trace", `${payload.steps.length} steps · ${payload.summary.layers} layers`, true, (performance.now() - started) / 1000);
        });
      },

      streamTrace: ({ delayMs, maxSteps }) => {
        let closed = false;
        setTrace(null);
        setLiveStep(null);
        setLoading((state) => ({ ...state, stream: true }));
        const handle = openTraceStream(
          {
            source: selectionRef.current,
            depth: settings.traceDepth,
            term_limit: settings.termLimit,
            max_steps: maxSteps ?? null,
            analyze_last_only: true,
            delay_ms: delayMs,
          },
          {
            onStep: (step, index) => {
              if (!closed) setLiveStep({ step, index });
            },
            onDone: () => {
              setLoading((state) => ({ ...state, stream: false }));
              note("live trace", "stream finished");
            },
            onError: (message) => {
              setLoading((state) => ({ ...state, stream: false }));
              setErrors((state) => ({ ...state, stream: message }));
              note("live trace", message, false);
            },
          },
        );
        return {
          close: () => {
            closed = true;
            setLoading((state) => ({ ...state, stream: false }));
            handle.close();
          },
        };
      },

      optimize: async () => {
        await runFor("optimize", async () => {
          const started = performance.now();
          const payload = await api.optimize({
            source: selectionRef.current,
            level: settings.optimizerLevel,
            verify: settings.verify,
          });
          setOptimization(payload);
          note(
            "optimize",
            payload.headline || `${payload.before.gates} → ${payload.after.gates} gates · ${payload.verification.status}`,
            payload.verification.status !== "VERIFICATION_FAILED",
            (performance.now() - started) / 1000,
          );
        });
      },

      compare: async (other) => {
        await runFor("compare", async () => {
          const started = performance.now();
          const payload = await api.compare({
            a: selectionRef.current,
            b: other,
            shots: settings.shots,
            seed: settings.seed,
            noise: resolvedNoise(),
            backend: settings.backend,
          });
          setCompareResult(payload);
          note("compare", payload.verdict.join(" "), true, (performance.now() - started) / 1000);
        });
      },

      runWhatIf: async (modification) => {
        await runFor("whatif", async () => {
          const started = performance.now();
          const payload = await api.whatIf({
            source: selectionRef.current,
            modification,
            shots: settings.shots,
            seed: settings.seed,
            backend: settings.backend,
            noise: resolvedNoise(),
          });
          setWhatIf(payload);
          note("what-if", `${String(modification.kind)}: ${payload.headline}`, true, (performance.now() - started) / 1000);
        });
      },

      analyseHardware: async (device, route) => {
        await runFor("hardware", async () => {
          const started = performance.now();
          const payload = await api.hardware({ source: selectionRef.current, device, route });
          setHardware(payload);
          note(
            "hardware analysis",
            `${device} · ${payload.fits ? "fits" : "does not fit"} · ${payload.connectivity_violations.length} violations`,
            true,
            (performance.now() - started) / 1000,
          );
        });
      },

      evolve: async (generations, population) => {
        await runFor("evolve", async () => {
          const started = performance.now();
          const payload = await api.evolve({
            source: selectionRef.current,
            generations,
            population,
            seed: settings.seed,
          });
          setEvolution(payload);
          note("evolve", payload.headline, true, (performance.now() - started) / 1000);
        });
      },

      runExperiment: async (request) => {
        await runFor("experiment", async () => {
          const started = performance.now();
          const payload = await api.runExperiment(request);
          setExperiment(payload);
          note("experiment", `${payload.rows.length} points: ${payload.headline}`, true, (performance.now() - started) / 1000);
          void api.history({ limit: 20 }).then((page) => setHistory(page.experiments));
        });
      },

      streamExperiment: (request) => {
        let closed = false;
        setExperiment(null);
        setExperimentProgress(null);
        setLoading((state) => ({ ...state, experiment: true }));
        const handle = openExperimentStream(request, {
          onStart: (event) => {
            if (!closed) setExperimentProgress({ index: 0, total: event.total, label: "starting" });
          },
          onProgress: (event) => {
            if (!closed) setExperimentProgress({ index: event.index, total: event.total, label: event.label });
          },
          onDone: (outcome) => {
            setLoading((state) => ({ ...state, experiment: false }));
            setExperimentProgress(null);
            setExperiment(outcome);
            note("experiment (live)", `${outcome.rows.length} points: ${outcome.headline}`);
            void api.history({ limit: 20 }).then((page) => setHistory(page.experiments));
          },
          onError: (message) => {
            setLoading((state) => ({ ...state, experiment: false }));
            setExperimentProgress(null);
            setErrors((state) => ({ ...state, experiment: message }));
            note("experiment (live)", message, false);
          },
        });
        return {
          close: () => {
            closed = true;
            setLoading((state) => ({ ...state, experiment: false }));
            setExperimentProgress(null);
            handle.close();
          },
        };
      },

      exportReport: async (request, format) => {
        await runFor("report", async () => {
          const blob = await api.reportExport(request, format);
          const stem = (request.title ?? request.kind).replace(/[^A-Za-z0-9._-]+/g, "-").slice(0, 80) || "qscope-report";
          downloadBlob(blob, `${stem}.${format === "markdown" ? "md" : format}`);
          note("export", `${request.kind} report · ${format} · ${(blob.size / 1024).toFixed(1)} KB`);
        });
      },

      runBenchmark: async (request) => {
        await runFor("benchmark", async () => {
          const started = performance.now();
          const payload = await api.benchmark(request as Parameters<typeof api.benchmark>[0]);
          setBenchmark(payload);
          note("benchmark", `${String(payload.kind)} measured`, true, (performance.now() - started) / 1000);
        });
      },

      ask: async (body) => {
        await runFor("ask", async () => {
          const started = performance.now();
          const payload = await api.ask(body);
          setAnswer(payload);
          note("ask", `${payload.intent}: ${payload.title}`, true, (performance.now() - started) / 1000);
        });
      },

      buildReport: async (kind, payload, title, objective) => {
        await runFor("report", async () => {
          const started = performance.now();
          const response = await api.report({ kind, payload, title, objective, save: true });
          setReport(response);
          note("report", `${kind} report · ${Object.keys(response.files ?? {}).length} files`, true, (performance.now() - started) / 1000);
        });
      },

      refreshHistory: async (params) => {
        await runFor("history", async () => {
          const payload = await api.history(params ?? { limit: 50 });
          setHistory(payload.experiments);
        });
      },

      deleteStored: async (id) => {
        await runFor("history", async () => {
          await api.historyDelete(id);
          const payload = await api.history({ limit: 50 });
          setHistory(payload.experiments);
          note("history", `deleted ${id}`);
        });
      },

      reproduce: async (id) => {
        let outcome: Awaited<ReturnType<typeof api.historyReproduce>> | null = null;
        await runFor("history", async () => {
          outcome = await api.historyReproduce(id);
          note("reproduce", `${id}: ${outcome.verdict}`);
        });
        return outcome;
      },
    };
  }, [
    answer,
    benchmark,
    compareResult,
    document,
    errors,
    evolution,
    experiment,
    experimentId,
    experimentProgress,
    hardware,
    health,
    history,
    liveStep,
    loading,
    log,
    meta,
    note,
    optimization,
    plan,
    report,
    result,
    run,
    selection,
    setSettings,
    setSource,
    settings,
    trace,
    whatIf,
    resolvedNoise,
  ]);

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): StoreValue {
  const context = useContext(StoreContext);
  if (!context) throw new Error("useStore must be used inside <StoreProvider>");
  return context;
}

/** The state metrics of the most recent executed run, if there is one. */
export function useCurrentMetrics(): { metrics: StateMetrics | null; mode: Mode | null } {
  const { result } = useStore();
  if (result) return { metrics: result.metrics, mode: result.mode };
  return { metrics: null, mode: null };
}
