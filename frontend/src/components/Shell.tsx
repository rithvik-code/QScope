/**
 * The shell: mode navigation, environment strip, palette studio and the run log.
 *
 * The navigation follows the workflow the platform is built around —
 * build → execute → trace → analyze → optimize → experiment → benchmark →
 * research — with mission control in front of it and the noise observatory beside
 * the optimizer, because those are the two instruments you reach for while
 * working rather than after.
 */

import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useTheme } from "../theme/ThemeProvider";
import { PALETTES } from "../theme/theme";
import { useStore } from "../state/store";
import { Button, Panel, Segmented, Tag } from "./ui";
import { PulseDot } from "./motion";

export type ModeKey =
  | "control"
  | "build"
  | "execute"
  | "trace"
  | "analyze"
  | "optimize"
  | "noise"
  | "experiment"
  | "benchmark"
  | "research";

export const MODES: Array<{ key: ModeKey; label: string; stage: string; blurb: string; icon: IconName }> = [
  { key: "control", label: "Mission Control", stage: "00", blurb: "The state of the whole environment, and the workflow map.", icon: "radar" },
  { key: "build", label: "Build", stage: "01", blurb: "Compose a circuit from gates, algorithms or QASM.", icon: "circuit" },
  { key: "execute", label: "Execute", stage: "02", blurb: "Run it and read the result with its provenance.", icon: "play" },
  { key: "trace", label: "Trace", stage: "03", blurb: "The quantum time machine: state after every gate.", icon: "steps" },
  { key: "analyze", label: "Analyze", stage: "04", blurb: "Metrics, entanglement, comparison and what-if.", icon: "chart" },
  { key: "optimize", label: "Optimize", stage: "05", blurb: "Verified rewrites, circuit evolution, hardware mapping.", icon: "wand" },
  { key: "noise", label: "Noise", stage: "06", blurb: "Error models, fidelity degradation and device estimates.", icon: "wave" },
  { key: "experiment", label: "Experiment", stage: "07", blurb: "Sweeps, reproducibility and stored history.", icon: "flask" },
  { key: "benchmark", label: "Benchmark", stage: "08", blurb: "Measured runtime, memory and scaling.", icon: "gauge" },
  { key: "research", label: "Research", stage: "09", blurb: "The grounded assistant and report generator.", icon: "book" },
];

type IconName =
  | "radar"
  | "circuit"
  | "play"
  | "steps"
  | "chart"
  | "wand"
  | "wave"
  | "flask"
  | "gauge"
  | "book"
  | "palette"
  | "log"
  | "pulse";

const ICONS: Record<IconName, ReactNode> = {
  radar: (
    <>
      <circle cx="8" cy="8" r="6" />
      <circle cx="8" cy="8" r="2.4" />
      <path d="M8 2v3M8 11v3M2 8h3M11 8h3" />
    </>
  ),
  circuit: (
    <>
      <path d="M2 5h12M2 11h12" />
      <rect x="4.5" y="2.6" width="3" height="4.8" rx="1" />
      <rect x="9.5" y="8.6" width="3" height="4.8" rx="1" />
    </>
  ),
  play: <path d="M5 3.4l7 4.6-7 4.6z" />,
  steps: (
    <>
      <path d="M2 13h4V9h4V5h4" />
      <circle cx="13.5" cy="4.5" r="1.4" />
    </>
  ),
  chart: (
    <>
      <path d="M2 13h12" />
      <path d="M3.5 10.5l3-3 2.6 2.2L13 4.5" />
    </>
  ),
  wand: (
    <>
      <path d="M3 13l8-8" />
      <path d="M11 3l1 1-1 1-1-1z" />
      <path d="M5.6 5.4l.8.8M8 8l.8.8" />
    </>
  ),
  wave: <path d="M1.5 8c1.4-4 2.8-4 4.2 0s2.8 4 4.2 0 2.8-4 4.2 0" />,
  flask: (
    <>
      <path d="M6 2h4v3l3 6.4A1.6 1.6 0 0111.6 13H4.4A1.6 1.6 0 013 11.4L6 5z" />
      <path d="M5 9h6" />
    </>
  ),
  gauge: (
    <>
      <path d="M2.4 11a6 6 0 1111.2 0" />
      <path d="M8 11l3-3.4" />
    </>
  ),
  book: (
    <>
      <path d="M2.5 3.2h4.2A1.8 1.8 0 018.5 5v8a1.5 1.5 0 00-1.5-1.5H2.5z" />
      <path d="M13.5 3.2H9.3A1.8 1.8 0 008.5 5v8a1.5 1.5 0 011.5-1.5h3.5z" />
    </>
  ),
  palette: (
    <>
      <path d="M8 2a6 6 0 000 12c.9 0 1.2-.6 1.2-1.2 0-.9.7-1.4 1.5-1.4h1.1A2.2 2.2 0 0014 9.2C14 5.2 11.3 2 8 2z" />
      <circle cx="5.8" cy="7" r="0.9" />
      <circle cx="8.4" cy="5.4" r="0.9" />
    </>
  ),
  log: (
    <>
      <path d="M3 3h10v10H3z" />
      <path d="M5 6h6M5 8.5h6M5 11h3" />
    </>
  ),
  pulse: <path d="M1 8h3l1.5-4 2.5 8 2-5 1 1h4" />,
};

export function Icon({ name, size = 15 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {ICONS[name]}
    </svg>
  );
}

// ------------------------------------------------------------- PaletteStudio

function PaletteStudio({ onClose }: { onClose: () => void }) {
  const theme = useTheme();
  const [copied, setCopied] = useState(false);
  return (
    <motion.aside
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
      className="pointer-events-auto absolute right-3 top-14 z-30 w-[320px]"
    >
      <Panel
        title="Palette studio"
        subtitle="Realtime Colors token model — five decisions, everything else derived."
        actions={
          <Button size="sm" variant="ghost" onClick={onClose}>
            close
          </Button>
        }
      >
        <div className="space-y-3">
          <div className="grid grid-cols-5 gap-1.5">
            {(["text", "background", "primary", "secondary", "accent"] as const).map((key) => (
              <label key={key} className="space-y-1 text-center">
                <input
                  type="color"
                  value={theme.colors[key]}
                  onChange={(event) => theme.setColor(key, event.target.value)}
                  className="h-9 w-full cursor-pointer rounded-md border border-[var(--c-line)] bg-transparent"
                  aria-label={`${key} colour`}
                />
                <span className="label-xs block">{key.slice(0, 5)}</span>
              </label>
            ))}
          </div>

          <div className="flex items-center justify-between text-[11px]">
            <span className="text-[var(--c-muted)]">text on background</span>
            <Tag colour={theme.contrast >= 4.5 ? "var(--c-ok)" : "var(--c-danger)"}>
              {theme.contrast.toFixed(2)}:1 {theme.contrast >= 4.5 ? "readable" : "low contrast"}
            </Tag>
          </div>

          <div className="space-y-1.5">
            <span className="label-xs">presets</span>
            <div className="flex flex-wrap gap-1.5">
              {PALETTES.map((palette) => (
                <button
                  key={palette.name}
                  type="button"
                  title={palette.note}
                  onClick={() => theme.applyPalette(palette)}
                  className={`focus-ring flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] transition-colors ${
                    theme.paletteName === palette.name
                      ? "border-[var(--c-primary)] text-[var(--c-primary)]"
                      : "border-[var(--c-line)] text-[var(--c-muted)] hover:text-[var(--c-text)]"
                  }`}
                >
                  <span className="flex">
                    {[palette.colors.background, palette.colors.primary, palette.colors.secondary, palette.colors.accent].map(
                      (colour) => (
                        <span key={colour} className="h-2.5 w-2.5 rounded-full" style={{ background: colour }} />
                      ),
                    )}
                  </span>
                  {palette.name}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={theme.randomise}>
              surprise me
            </Button>
            <Button size="sm" variant="ghost" onClick={theme.reset}>
              reset
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                void navigator.clipboard?.writeText(theme.shareUrl());
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1600);
              }}
            >
              {copied ? "link copied" : "share look"}
            </Button>
          </div>
          <p className="text-[10px] leading-relaxed text-[var(--c-faint)]">
            The palette is written to CSS variables, so changing it repaints the whole instrument —
            including every chart — without recomputing anything.
          </p>
        </div>
      </Panel>
    </motion.aside>
  );
}

// ------------------------------------------------------------------ RunLog

function RunLog() {
  const { log } = useStore();
  return (
    <Panel title="Run log" subtitle="What this session asked the engine for, newest first." dense>
      <div className="max-h-[280px] space-y-1 overflow-y-auto pr-1">
        {log.length === 0 && <p className="text-[11px] text-[var(--c-faint)]">Nothing yet — run something.</p>}
        {log.map((entry, index) => (
          <div key={index} className="flex items-start gap-2 border-b border-[color-mix(in_oklab,var(--c-line)_40%,transparent)] pb-1">
            <span className="mono-num shrink-0 text-[10px] text-[var(--c-faint)]">{entry.at}</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span
                  className="text-[11px] font-medium"
                  style={{ color: entry.ok ? "var(--c-text)" : "var(--c-danger)" }}
                >
                  {entry.action}
                </span>
                {entry.seconds !== undefined && (
                  <span className="mono-num text-[10px] text-[var(--c-faint)]">{entry.seconds.toFixed(3)} s</span>
                )}
              </div>
              <p className="truncate text-[10px] text-[var(--c-muted)]" title={entry.detail}>
                {entry.detail}
              </p>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ------------------------------------------------------------------- Shell

export function Shell({
  mode,
  onModeChange,
  children,
}: {
  mode: ModeKey;
  onModeChange: (mode: ModeKey) => void;
  children: ReactNode;
}) {
  const { health, meta, result, trace, selection, document: circuit } = useStore();
  const [showPalette, setShowPalette] = useState(false);
  const active = MODES.find((entry) => entry.key === mode) ?? MODES[0];

  return (
    <div className="relative flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_86%,transparent)] backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[1680px] items-center gap-4 px-4 py-2.5">
          <div className="flex items-center gap-2.5">
            <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
              <rect width="32" height="32" rx="8" fill="color-mix(in oklab, var(--c-primary) 16%, transparent)" />
              <circle cx="16" cy="16" r="7.5" fill="none" stroke="var(--c-primary)" strokeWidth="1.6" />
              <circle cx="16" cy="16" r="2.4" fill="var(--c-primary)" />
              <ellipse cx="16" cy="16" rx="11.5" ry="4.2" fill="none" stroke="var(--c-secondary)" strokeWidth="1" strokeOpacity="0.85" />
            </svg>
            <div className="leading-none">
              <div className="text-[14px] font-semibold tracking-tight">QScope</div>
              <div className="mt-0.5 text-[10px] text-[var(--c-faint)]">see inside quantum computing</div>
            </div>
          </div>

          <div className="mx-2 hidden h-7 w-px bg-[var(--c-line)] lg:block" />

          <div className="hidden min-w-0 flex-1 items-center gap-2 lg:flex">
            <Tag colour="var(--c-secondary)">
              {active.stage} {active.label}
            </Tag>
            <span className="truncate text-[11px] text-[var(--c-muted)]">{active.blurb}</span>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <span className="hidden items-center gap-1.5 text-[10px] text-[var(--c-muted)] md:flex">
              <PulseDot colour={health ? "var(--c-ok)" : "var(--c-warn)"} />
              {health ? `${health.version} · ${health.numpy}` : "connecting"}
            </span>
            <Tag colour={health?.llm_configured ? "var(--c-accent)" : "var(--c-muted)"} title={health?.llm_configured ? "An LLM endpoint is configured for narration" : "Fully offline: the assistant answers from your own data"}>
              {health?.llm_configured ? "llm: configured" : "offline"}
            </Tag>
            <Tag title="Circuit currently loaded">
              {circuit ? `${circuit.num_qubits}q · ${circuit.resources.gates}g` : "—"}
            </Tag>
            {result && (
              <Tag colour={result.mode === "NOISY SIMULATION" ? "var(--c-warn)" : "var(--c-ok)"} title="Most recent executed run">
                last: {result.mode}
              </Tag>
            )}
            <Button size="sm" variant="outline" onClick={() => setShowPalette((value) => !value)}>
              <Icon name="palette" size={13} />
              palette
            </Button>
          </div>
        </div>

        {/* workflow rail */}
        <nav className="mx-auto flex w-full max-w-[1680px] items-center gap-1 overflow-x-auto px-4 pb-2">
          {MODES.map((entry) => {
            const isActive = entry.key === mode;
            return (
              <button
                key={entry.key}
                type="button"
                onClick={() => onModeChange(entry.key)}
                className={`focus-ring group relative flex shrink-0 items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px] transition-colors ${
                  isActive ? "text-[var(--c-text)]" : "text-[var(--c-muted)] hover:text-[var(--c-text)]"
                }`}
              >
                {isActive && (
                  <motion.span
                    layoutId="mode-pill"
                    className="absolute inset-0 rounded-lg border border-[var(--c-primary)] bg-[color-mix(in_oklab,var(--c-primary)_12%,transparent)]"
                    transition={{ type: "spring", stiffness: 420, damping: 34 }}
                  />
                )}
                <span className="relative flex items-center gap-2">
                  <Icon name={entry.icon} size={14} />
                  <span className="hidden sm:inline">{entry.label}</span>
                </span>
              </button>
            );
          })}
          <span className="ml-auto hidden shrink-0 pr-1 text-[10px] text-[var(--c-faint)] xl:block">
            {trace ? `trace ready · ${trace.steps.length} steps` : selection.algorithm ? `source: ${selection.algorithm}` : "source: circuit"}
            {meta ? ` · ${meta.algorithms.length} algorithms` : ""}
          </span>
        </nav>
      </header>

      <main className="relative mx-auto w-full max-w-[1680px] flex-1 px-4 pb-16 pt-4">
        {children}
        <div className="mt-6 grid gap-3 lg:grid-cols-2">
          <RunLog />
          <Panel title="Data handling" subtitle="What the interface does and does not do with your numbers." dense>
            <ul className="space-y-1.5 text-[11px] leading-relaxed text-[var(--c-muted)]">
              <li>
                Every number shown comes from the Python engine and keeps the provenance attached to it —
                engine, representation, exactness, seed, shots, error model, timing and memory.
              </li>
              <li>
                Ideal, noisy and hardware-estimated results are labelled separately and are never merged into a
                single figure.
              </li>
              <li>
                The assistant can only quote the objects you give it; without an LLM configured it still answers,
                entirely offline.
              </li>
              <li>
                Benchmarks are wall-clock measurements on this machine. They are not a claim about quantum hardware,
                and no quantum advantage is reported anywhere.
              </li>
            </ul>
          </Panel>
        </div>
      </main>

      <AnimatePresence>{showPalette && <PaletteStudio onClose={() => setShowPalette(false)} />}</AnimatePresence>

      <footer className="border-t border-[var(--c-line)] px-4 py-3">
        <div className="mx-auto flex w-full max-w-[1680px] items-center justify-between text-[10px] text-[var(--c-faint)]">
          <span>
            QScope {health?.version ?? "0.1.0"} · python {health?.python ?? "—"} · numpy {health?.numpy ?? "—"} ·
            history {health?.experiments_stored ?? 0} runs
          </span>
          <span className="mono-num hidden sm:block">{health?.database ?? ""}</span>
        </div>
      </footer>
    </div>
  );
}

export { Segmented };
