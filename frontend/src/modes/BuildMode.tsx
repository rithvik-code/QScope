/**
 * Build — the circuit IDE.
 *
 * The editor is a thin, honest layer over the engine: it edits an operation list
 * locally and then asks the backend for the authoritative document (resources,
 * depth, layer count, diagram, QASM).  Nothing is estimated client-side, so the
 * numbers in the header are the same ones a run will use.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { FieldGuide } from "../components/Guide";
import { api, downloadBlob, type CircuitDraft } from "../lib/api";
import { Button, CodeBlock, Field, IconButton, Notice, NumberInput, Panel, SectionTitle, Segmented, Select, Tag } from "../components/ui";
import { CircuitCanvas } from "../components/viz/quantum";
import { useStore } from "../state/store";
import type { ModeKey } from "../components/Shell";
import type { CircuitOperation } from "../lib/api";

const GATE_GROUPS: Array<{ group: string; gates: Array<{ name: string; label: string; params?: number[]; arity: number; hint: string }> }> = [
  {
    group: "single qubit",
    gates: [
      { name: "H", label: "H", arity: 1, hint: "Hadamard — creates superposition" },
      { name: "X", label: "X", arity: 1, hint: "bit flip" },
      { name: "Y", label: "Y", arity: 1, hint: "bit + phase flip" },
      { name: "Z", label: "Z", arity: 1, hint: "phase flip" },
      { name: "S", label: "S", arity: 1, hint: "√Z" },
      { name: "SDG", label: "S†", arity: 1, hint: "inverse √Z" },
      { name: "T", label: "T", arity: 1, hint: "√S — a non-Clifford phase" },
      { name: "TDG", label: "T†", arity: 1, hint: "inverse √S" },
      { name: "SX", label: "√X", arity: 1, hint: "square root of X" },
    ],
  },
  {
    group: "rotations",
    gates: [
      { name: "RX", label: "Rx(θ)", params: [1.5707963], arity: 1, hint: "rotation about x" },
      { name: "RY", label: "Ry(θ)", params: [1.5707963], arity: 1, hint: "rotation about y" },
      { name: "RZ", label: "Rz(θ)", params: [1.5707963], arity: 1, hint: "rotation about z" },
      { name: "P", label: "P(φ)", params: [0.7853982], arity: 1, hint: "phase gate" },
    ],
  },
  {
    group: "two qubits & more",
    gates: [
      { name: "CNOT", label: "CNOT", arity: 2, hint: "control on the first wire, target on the second" },
      { name: "CZ", label: "CZ", arity: 2, hint: "controlled phase" },
      { name: "SWAP", label: "SWAP", arity: 2, hint: "exchange two qubits" },
      { name: "ISWAP", label: "iSWAP", arity: 2, hint: "swap with a phase" },
      { name: "TOFFOLI", label: "Toffoli", arity: 3, hint: "doubly controlled X" },
    ],
  },
  {
    group: "non-unitary",
    gates: [
      { name: "measure", label: "Measure", arity: 1, hint: "project and record one qubit" },
      { name: "reset", label: "Reset", arity: 1, hint: "return a qubit to |0⟩" },
      { name: "barrier", label: "Barrier", arity: 1, hint: "mark a scheduling boundary" },
    ],
  },
];

const PRESETS: Array<{ key: string; label: string }> = [
  { key: "bell", label: "Bell pair" },
  { key: "ghz", label: "GHZ" },
  { key: "superposition", label: "Uniform superposition" },
  { key: "teleport", label: "Teleportation" },
];

const GUIDED_TEMPLATES = [
  { key: "bell_state", title: "Bell pair", note: "Your first entangled pair", description: "A Hadamard and a controlled-X create correlations that cannot be explained as two independent qubits.", qubits: "2 qubits · 2 gates" },
  { key: "ghz_state", title: "GHZ state", note: "Entanglement across a register", description: "Extend the Bell-state idea to several qubits and explore how shared correlations scale.", qubits: "3 qubits · multi-qubit" },
  { key: "grover", title: "Grover search", note: "Amplitude amplification", description: "See how repeated reflections raise the probability of a marked answer.", qubits: "small search register" },
  { key: "teleportation", title: "Teleportation", note: "A quantum protocol", description: "Follow entanglement, measurement, and classical feed-forward in a complete protocol.", qubits: "3 qubits · measurements" },
];

export function BuildMode({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const { meta, document: circuit, selection, loading, errors, loadAlgorithm, loadQasm, resetCircuit, editCircuit, setQubitCount, setSource, setSettings, planRun, runPanic, note, undoCircuit, redoCircuit, canUndo, canRedo, settings, result } =
    useStore();
  const [selected, setSelected] = useState<number | null>(null);
  const [view, setView] = useState<"diagram" | "qasm">("diagram");
  const [qubits, setQubits] = useState(3);
  const [qasmInput, setQasmInput] = useState("");
  const [pendingGate, setPendingGate] = useState<string | null>(null);
  const [activeTemplate, setActiveTemplate] = useState(GUIDED_TEMPLATES[0]);
  const [targetWires, setTargetWires] = useState<number[]>([0, 1]);
  const [drafts, setDrafts] = useState<CircuitDraft[]>([]);
  const [activeDraft, setActiveDraft] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [versions, setVersions] = useState<Array<{ version: number; saved_at: string }>>([]);
  const [draggedOperation, setDraggedOperation] = useState<number | null>(null);
  const projectFile = useRef<HTMLInputElement>(null);

  const refreshDrafts = async () => {
    const payload = await api.drafts();
    setDrafts(payload.drafts);
  };

  useEffect(() => { void refreshDrafts().catch((error) => note("drafts", (error as Error).message, false)); }, []);

  const saveDraft = async () => {
    if (!circuit) return;
    const name = draftName.trim() || circuit.name || "Untitled circuit";
    await runPanic("draft", async () => {
      const saved = activeDraft
        ? await api.draftUpdate(activeDraft, { name, circuit })
        : await api.draftCreate({ name, circuit });
      setActiveDraft(saved.draft_id);
      setDraftName(saved.name);
      await refreshDrafts();
      note("save draft", `${saved.name} · version ${saved.version}`);
    });
  };

  const loadDraft = async (draft: CircuitDraft) => {
    await runPanic("draft", async () => {
      const full = await api.draftGet(draft.draft_id);
      if (!full?.document) throw new Error("This draft has no saved circuit.");
      await setSource({ circuit: full.document });
      setActiveDraft(draft.draft_id); setDraftName(draft.name);
      const revisionList = await api.draftVersions(draft.draft_id); setVersions(revisionList.versions);
      note("load draft", `${draft.name} · version ${draft.version}`);
    });
  };

  const exportProject = async () => {
    if (!circuit) return;
    await runPanic("project", async () => {
      const blob = await api.projectExport({ name: draftName.trim() || circuit.name, circuit, settings: settings as unknown as Record<string, unknown>, last_run: result as unknown as Record<string, unknown> | null });
      downloadBlob(blob, `${(draftName.trim() || circuit.name).replace(/[^a-z0-9-_]+/gi, "-")}.qscope.json`);
      note("export project", circuit.name);
    });
  };

  const importProject = async (file?: File) => {
    if (!file) return;
    await runPanic("project", async () => {
      const project = JSON.parse(await file.text());
      const imported = await api.projectImport(project);
      await setSource({ circuit: imported.circuit });
      setSettings(imported.settings as Parameters<typeof setSettings>[0]);
      setDraftName(imported.name); setActiveDraft(null);
      note("import project", `${imported.name} · ${imported.circuit.num_qubits} qubits`);
    });
    if (projectFile.current) projectFile.current.value = "";
  };

  const selectedOperation = useMemo(
    () => (circuit && selected !== null ? circuit.operations[selected] ?? null : null),
    [circuit, selected],
  );

  const addGate = async (name: string, params: number[] | undefined) => {
    if (!circuit) return;
    const arity = GATE_GROUPS.flatMap((group) => group.gates).find((gate) => gate.name === name)?.arity ?? 1;
    const selectedValid = targetWires.filter((wire) => wire < circuit.num_qubits);
    const wires = [...selectedValid, ...Array.from({ length: circuit.num_qubits }, (_, wire) => wire).filter((wire) => !selectedValid.includes(wire))].slice(0, arity);
    if (name === "measure" || name === "reset" || name === "barrier") {
      await editCircuit((operations) => {
        operations.push({
          name,
          targets: [wires[0] ?? 0],
          params: [],
          controls: [],
          classical_targets: name === "measure" ? [wires[0] ?? 0] : [],
          kind: name === "measure" || name === "reset" || name === "barrier" ? name : "gate",
          label: "",
          opid: `local-${Date.now()}-${operations.length}`,
        } as CircuitOperation);
        return operations;
      });
      note("edit", `added ${name} on q${wires[0] ?? 0}`);

      return;
    }
    if (arity > circuit.num_qubits) {
      note("edit", `${name} needs ${arity} qubits but the circuit has ${circuit.num_qubits}`, false);
      return;
    }
    await editCircuit((operations) => {
      operations.push({
        name,
        targets: wires.slice(0, Math.max(arity, 1)),
        params: params ?? [],
        controls: [],
        kind: "gate",
        label: "",
        opid: `local-${Date.now()}-${operations.length}`,
      } as CircuitOperation);
      return operations;
    });
    note("edit", `added ${name}${params ? `(${params.map((p) => p.toFixed(3)).join(",")})` : ""} on ${wires.slice(0, Math.max(arity, 1)).map((w) => `q${w}`).join(",")}`);
  };

  return (
    <div className="space-y-4">
      <FieldGuide
        modeName="Build"
        slides={[
          {
            heading: "What you are looking at",
            steps: [
              {
                title: "Bottom-left is where you build",
                body: "Use the Sources panel to pick an algorithm from the catalogue, a built-in template, paste OpenQASM 2.0, or start with an empty register. The Gate palette below it is how you add gates: click a gate to append it to q0…q{n-1}.",
                pointer: "gate palette → click a gate like H, CNOT, RX",
              },
              {
                title: "The canvas is the circuit, not a decoration",
                body: "The upper panel shows your circuit diagram. Switch to the QASM tab to see the same circuit as text. When you add a gate in the palette or the operation list, the diagram updates — there is no separate ‘apply’ step.",
                pointer: "canvas caption → diagram / QASM toggle, plan this run, execute →",
              },
              {
                title: "The operation list is where edits become real",
                body: "Click any gate here (or on the canvas) to inspect it. You can change its targets, controls, and parameters, move it up or down, or delete it. Every edit is re-validated by the engine, so a gate on a wire that does not exist is refused rather than silently accepted.",
                pointer: "operation list → select a row, edit targets / controls / parameters",
                tip: "shared selection → trace",
              },
            ],
          },
          {
            heading: "How to actually use this page",
            steps: [
              {
                title: "Start from something, not from nothing",
                body: "The fastest way in is a preset or an algorithm. ‘Bell pair’ loads a 2-qubit entangled circuit in one click; ‘GHZ’ scales to however many qubits you ask for; ‘Uniform superposition’ gives every basis state equal weight.",
                pointer: "Sources → templates, or algorithm dropdown",
                highlight: 2,
                tip: "qubits to start with",
              },
              {
                title: "One qubit is not enough to see anything interesting",
                body: "Entanglement, multi-qubit gates, and most algorithms need at least two qubits. Use ‘add a wire’ or the register-size box to grow the circuit; ‘resize’ drops operations that touch a removed wire.",
                pointer: "Sources → register size, or add a wire",
              },
            ],
          },
        ]}
      />

      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)_250px]">
        {/* -------------------------------------------------- gate palette */}
        <div className="space-y-3">
          <Panel title="Sources" subtitle="Start from an algorithm, a template, QASM or an empty register." dense>
            <div className="space-y-2.5">
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => projectFile.current?.click()}>Import project</Button>
                <Button size="sm" variant="outline" disabled={!circuit} onClick={() => void exportProject()}>Export project</Button>
                <input ref={projectFile} type="file" accept=".json,.qscope.json,application/json" className="hidden" onChange={(event) => void importProject(event.target.files?.[0])} />
              </div>
              <Field label="algorithm">
                <Select
                  value=""
                  options={[
                    { value: "", label: "— choose one —" },
                    ...(meta?.algorithms ?? []).map((algorithm) => ({ value: algorithm.key, label: algorithm.name })),
                  ]}
                  onChange={(value) => {
                    if (value) void loadAlgorithm(value);
                  }}
                />
              </Field>
              <Field label="template">
                <div className="flex flex-wrap gap-1.5">
                  {PRESETS.map((preset) => (
                    <Button
                      key={preset.key}
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        if (preset.key === "bell") void loadAlgorithm("bell_state");
                        else if (preset.key === "ghz") void loadAlgorithm("ghz_state", { num_qubits: qubits });
                        else if (preset.key === "teleport") void loadAlgorithm("teleportation");
                        else
                          void runPanic("template", async () => {
                            const loaded = await api.fromQasm(superpositionQasm(qubits));
                            await setSource({ circuit: loaded });
                            note("template", `uniform superposition on ${qubits} qubits`);
                          });
                      }}
                    >
                      {preset.label}
                    </Button>
                  ))}
                </div>
              </Field>
              <Field label="register size" hint="Changing this drops operations that touch removed wires.">
                <div className="flex items-center gap-2">
                  <NumberInput value={qubits} min={1} max={24} onChange={setQubits} />
                  <Button size="sm" variant="outline" onClick={() => void resetCircuit(qubits)}>
                    new
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void setQubitCount(qubits)}>
                    resize
                  </Button>
                </div>
              </Field>
              {circuit && (
                <Field label="grow by one qubit">
                  <Button size="sm" variant="outline" onClick={() => void setQubitCount(circuit.num_qubits + 1)}>
                    add a wire
                  </Button>
                </Field>
              )}
            </div>
          </Panel>

          <Panel title="Gate palette" subtitle="Choose the wire(s), then click a gate." dense>
            <div className="space-y-3">
              {circuit && <div className="flex flex-wrap items-center gap-1.5"><span className="label-xs mr-1">Wires</span>{Array.from({ length: circuit.num_qubits }, (_, wire) => <button key={wire} type="button" aria-pressed={targetWires.includes(wire)} onClick={() => setTargetWires((current) => current.includes(wire) ? current.filter((item) => item !== wire) : [...current, wire])} className={`rounded-md border px-2 py-1 text-[10px] ${targetWires.includes(wire) ? "border-[var(--c-primary)] text-[var(--c-primary)]" : "border-[var(--c-line)] text-[var(--c-muted)]"}`}>q{wire}</button>)}</div>}
              {GATE_GROUPS.map((group) => (
                <div key={group.group}>
                  <SectionTitle>{group.group}</SectionTitle>
                  <div className="flex flex-wrap gap-1.5">
                    {group.gates.map((gate) => (
                      <button
                        key={gate.name}
                        type="button"
                        title={gate.hint}
                        onClick={() => void addGate(gate.name, gate.params)}
                        className={`focus-ring mono-num rounded-md border px-2 py-1 text-[11px] transition-colors ${
                          pendingGate === gate.name
                            ? "border-[var(--c-primary)] text-[var(--c-primary)]"
                            : "border-[var(--c-line)] text-[var(--c-muted)] hover:border-[var(--c-primary)] hover:text-[var(--c-text)]"
                        }`}
                        onMouseEnter={() => setPendingGate(gate.name)}
                        onMouseLeave={() => setPendingGate(null)}
                      >
                        {gate.label}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        {/* ------------------------------------------------------- canvas */}
        <div className="space-y-3">
          <Panel
            title={circuit ? `${circuit.name} — ${circuit.num_qubits} qubits, ${circuit.num_clbits} classical bits` : "Circuit"}
            subtitle="Click a gate to inspect or edit it. Wires and layers come from the engine's own resource report."
            actions={
              <>
                <Segmented
                  value={view}
                  options={[
                    { value: "diagram", label: "canvas" },
                    { value: "qasm", label: "QASM" },
                  ]}
                  onChange={setView}
                  size="sm"
                />
                <Button size="sm" variant="outline" onClick={() => void planRun()}>
                  plan this run
                </Button>
                <Button size="sm" variant="primary" onClick={() => onNavigate("execute")}>
                  execute →
                </Button>
              </>
            }
          >
            {errors.edit && (
              <div className="mb-2">
                <Notice tone="danger" title="The engine rejected that edit">
                  {errors.edit}
                </Notice>
              </div>
            )}
            {loading.edit && <p className="mb-2 text-[10px] text-[var(--c-faint)]">re-validating…</p>}
            {view === "diagram" ? (
              <div className="overflow-hidden rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_60%,transparent)] p-2">
                <CircuitCanvas circuit={circuit} activeIndex={selected} onSelect={(index) => setSelected(index === selected ? null : index)} />
              </div>
            ) : (
              <CodeBlock text={circuit?.qasm ?? ""} maxHeight={340} caption="OpenQASM 2.0" />
            )}

            <div className="mt-3 grid gap-2 sm:grid-cols-6">
              {[
                { label: "gates", value: circuit?.resources.gates },
                { label: "depth", value: circuit?.resources.depth },
                { label: "2-qubit", value: circuit?.resources.two_qubit_gates },
                { label: "measure", value: circuit?.resources.measurements },
                { label: "parameters", value: circuit?.resources.parameters.length },
                { label: "clifford", value: circuit?.resources.is_clifford ? "yes" : "no" },
              ].map((stat) => (
                <div key={stat.label} className="panel-flat px-2.5 py-2">
                  <div className="label-xs">{stat.label}</div>
                  <div className="mono-num mt-0.5 text-[15px]">{String(stat.value ?? "—")}</div>
                </div>
              ))}
            </div>
          </Panel>

          <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
            <Panel title="Operation list" subtitle="Drag to reorder, or use the arrows. Undo and redo are available." dense actions={<div className="flex gap-1"><Button size="sm" variant="outline" disabled={!canUndo} onClick={() => void undoCircuit()}>↶ Undo</Button><Button size="sm" variant="outline" disabled={!canRedo} onClick={() => void redoCircuit()}>↷ Redo</Button></div>}>
              <div className="max-h-[300px] space-y-1 overflow-y-auto pr-1">
                {!circuit?.operations.length && <p className="text-[11px] text-[var(--c-faint)]">No operations yet.</p>}
                {circuit?.operations.map((operation, index) => (
                  <div
                    key={operation.opid ?? index}
                    draggable
                    onDragStart={() => setDraggedOperation(index)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={() => { if (draggedOperation === null || draggedOperation === index) return; void editCircuit((operations) => { const [item] = operations.splice(draggedOperation, 1); operations.splice(index, 0, item); return operations; }); setDraggedOperation(null); }}
                    className={`flex items-center gap-2 rounded-md border px-2 py-1.5 text-[11px] transition-colors ${
                      selected === index
                        ? "border-[var(--c-primary)] bg-[color-mix(in_oklab,var(--c-primary)_10%,transparent)]"
                        : "border-[var(--c-line)] hover:border-[var(--c-line-strong)]"
                    }`}
                  >
                    <span className="mono-num w-6 shrink-0 text-[var(--c-faint)]">#{index}</span>
                    <button type="button" className="focus-ring min-w-0 flex-1 truncate text-left" onClick={() => setSelected(index)}>
                      {operation.name}
                      {operation.params.length > 0 && (
                        <span className="text-[var(--c-muted)]">
                          ({operation.params.map((value) => value.toFixed(3)).join(", ")})
                        </span>
                      )}
                      <span className="ml-2 text-[10px] text-[var(--c-faint)]">
                        {[...operation.controls, ...operation.targets].map((wire) => `q${wire}`).join(" → ")}
                        {operation.condition ? ` · if c[${operation.condition.clbit}]=${operation.condition.value}` : ""}
                      </span>
                    </button>
                    <Tag>{operation.kind}</Tag>
                    <div className="flex gap-1">
                      <IconButton
                        label="move up"
                        disabled={index === 0}
                        onClick={() =>
                          void editCircuit((operations) => {
                            const [item] = operations.splice(index, 1);
                            operations.splice(index - 1, 0, item);
                            return operations;
                          })
                        }
                      >
                        ↑
                      </IconButton>
                      <IconButton
                        label="move down"
                        disabled={index === (circuit?.operations.length ?? 1) - 1}
                        onClick={() =>
                          void editCircuit((operations) => {
                            const [item] = operations.splice(index, 1);
                            operations.splice(index + 1, 0, item);
                            return operations;
                          })
                        }
                      >
                        ↓
                      </IconButton>
                      <IconButton
                        label="delete"
                        onClick={() => {
                          void editCircuit((operations) => operations.filter((_, position) => position !== index));
                          setSelected(null);
                        }}
                      >
                        ×
                      </IconButton>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            <div className="space-y-3">
              {selectedOperation ? (
                <Panel title={`Edit ${selectedOperation.name}`} subtitle={`operation #${selected}`} dense>
                  <div className="space-y-2.5">
                    <Field label="targets (comma separated)">
                      <input
                        className="mono-num w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2 py-1.5 text-[12px]"
                        defaultValue={selectedOperation.targets.join(", ")}
                        onBlur={(event) =>
                          void editCircuit((operations) => {
                            operations[selected!] = {
                              ...operations[selected!],
                              targets: event.target.value
                                .split(",")
                                .map((value) => Number(value.trim()))
                                .filter((value) => Number.isFinite(value)),
                            };
                            return operations;
                          })
                        }
                      />
                    </Field>
                    <Field label="controls (comma separated)">
                      <input
                        className="mono-num w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2 py-1.5 text-[12px]"
                        defaultValue={selectedOperation.controls.join(", ")}
                        onBlur={(event) =>
                          void editCircuit((operations) => {
                            operations[selected!] = {
                              ...operations[selected!],
                              controls: event.target.value
                                .split(",")
                                .map((value) => Number(value.trim()))
                                .filter((value) => Number.isFinite(value)),
                            };
                            return operations;
                          })
                        }
                      />
                    </Field>
                    <Field label="parameters (comma separated, radians)">
                      <input
                        className="mono-num w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2 py-1.5 text-[12px]"
                        defaultValue={selectedOperation.params.join(", ")}
                        onBlur={(event) =>
                          void editCircuit((operations) => {
                            operations[selected!] = {
                              ...operations[selected!],
                              params: event.target.value
                                .split(",")
                                .map((value) => Number(value.trim()))
                                .filter((value) => Number.isFinite(value)),
                            };
                            return operations;
                          })
                        }
                      />
                    </Field>
                    <p className="text-[10px] text-[var(--c-faint)]">
                      Every edit is re-validated by the engine; a gate on a wire that does not exist is refused rather
                      than silently accepted.
                    </p>
                  </div>
                </Panel>
              ) : (
                <Panel title="Inspect" subtitle="Nothing selected" dense>
                  <p className="text-[11px] text-[var(--c-muted)]">
                    Select a gate in the list or on the canvas to edit its wires and parameters. Selection is also
                    shared with the trace view, so you can jump straight to that gate's step.
                  </p>
                </Panel>
              )}

              <Panel title="Import QASM" subtitle="Paste OpenQASM 2.0" dense>
                <textarea
                  className="mono-num h-24 w-full resize-y rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] p-2 text-[11px]"
                  placeholder={'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];'}
                  value={qasmInput}
                  onChange={(event) => setQasmInput(event.target.value)}
                />
                <div className="mt-2 flex gap-2">
                  <Button size="sm" variant="primary" disabled={!qasmInput.trim()} onClick={() => void loadQasm(qasmInput)}>
                    import
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setQasmInput("")}>
                    clear
                  </Button>
                </div>
                {errors.load && (
                  <div className="mt-2">
                    <Notice tone="danger" title="Import failed">
                      {errors.load}
                    </Notice>
                  </div>
                )}
              </Panel>
            </div>
          </div>
        </div>

        {/* ----------------------------------------------- guided templates */}
        <aside className="space-y-3 xl:sticky xl:top-28 xl:self-start">
          <Panel title="Start from a template" subtitle="Choose a goal; the details stay attached." dense>
            <div className="space-y-1.5">
              {GUIDED_TEMPLATES.map((template) => (
                <button
                  key={template.key}
                  type="button"
                  onClick={() => setActiveTemplate(template)}
                  className={`focus-ring w-full rounded-lg border px-2.5 py-2 text-left transition-colors ${activeTemplate.key === template.key ? "border-[var(--c-primary)] bg-[color-mix(in_oklab,var(--c-primary)_9%,transparent)]" : "border-[var(--c-line)] hover:border-[var(--c-line-strong)]"}`}
                  aria-pressed={activeTemplate.key === template.key}
                >
                  <span className="block text-xs font-medium">{template.title}</span>
                  <span className="mt-0.5 block text-[10px] text-[var(--c-muted)]">{template.note}</span>
                </button>
              ))}
            </div>
            <div className="mt-3 rounded-lg bg-[var(--c-panel-2)] p-3">
              <div className="label-xs">{activeTemplate.qubits}</div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--c-muted)]">{activeTemplate.description}</p>
              <Button
                className="mt-3 w-full"
                size="sm"
                variant="primary"
                onClick={() => {
                  void loadAlgorithm(activeTemplate.key, activeTemplate.key === "ghz_state" ? { num_qubits: qubits } : {});
                }}
              >
                Use this template →
              </Button>
            </div>
            <p className="mt-2 text-[10px] leading-relaxed text-[var(--c-faint)]">Templates replace the current circuit. Your saved runs remain in History.</p>
          </Panel>
          <Panel title="What next?" dense>
            <div className="space-y-2 text-[11px] text-[var(--c-muted)]">
              <button type="button" className="block text-left hover:text-[var(--c-primary)]" onClick={() => onNavigate("execute")}>① Run it and see the outcome →</button>
              <button type="button" className="block text-left hover:text-[var(--c-primary)]" onClick={() => onNavigate("trace")}>② Trace how each gate changes the state →</button>
            </div>
          </Panel>
          <Panel title="Saved drafts" subtitle="Named circuits with recoverable versions." dense>
            <div className="space-y-2">
              <input value={draftName} onChange={(event) => setDraftName(event.target.value)} placeholder="Draft name" className="w-full rounded-md border border-[var(--c-line)] bg-[var(--c-panel-2)] px-2.5 py-2 text-xs" aria-label="Draft name" />
              <Button size="sm" variant="primary" className="w-full" disabled={!circuit} onClick={() => void saveDraft()}>{activeDraft ? "Save changes" : "Save current circuit"}</Button>
              {drafts.length ? drafts.map((draft) => <div key={draft.draft_id} className="flex items-center gap-1 rounded-lg border border-[var(--c-line)] p-2"><button type="button" onClick={() => void loadDraft(draft)} className="min-w-0 flex-1 text-left"><span className="block truncate text-xs">{draft.favorite ? "★ " : ""}{draft.name}</span><span className="text-[10px] text-[var(--c-faint)]">v{draft.version} · {new Date(draft.updated_at).toLocaleDateString()}</span></button><button type="button" title="Toggle favorite" onClick={() => void api.draftUpdate(draft.draft_id, { favorite: !draft.favorite }).then(refreshDrafts)} className="px-1 text-xs">{draft.favorite ? "★" : "☆"}</button><button type="button" title="Delete draft" onClick={() => { if (window.confirm(`Delete “${draft.name}” and its saved versions?`)) void api.draftDelete(draft.draft_id).then(refreshDrafts); }} className="px-1 text-xs text-[var(--c-muted)]">×</button></div>) : <p className="text-[10px] text-[var(--c-faint)]">Saved circuits will appear here.</p>}
              {activeDraft && versions.length > 0 && <div className="border-t border-[var(--c-line)] pt-2"><div className="label-xs mb-1">Version history</div>{versions.slice(0, 5).map((entry) => <button key={entry.version} type="button" onClick={() => void runPanic("draft", async () => { const restored = await api.draftRestore(activeDraft, entry.version); if (restored.document) await setSource({ circuit: restored.document }); await refreshDrafts(); setVersions((await api.draftVersions(activeDraft)).versions); note("restore draft version", `v${entry.version}`); })} className="mr-2 mb-1 rounded border border-[var(--c-line)] px-2 py-1 text-[10px]">Restore v{entry.version}</button>)}</div>}
            </div>
          </Panel>
        </aside>
      </div>

      {selection.qasm && (
        <Notice tone="info">
          The loaded source came from QASM text. Editing it converts the workspace to a circuit document, which is the
          form later stages use.
        </Notice>
      )}
    </div>
  );
}

/** A small helper so the template buttons do not need a separate algorithm entry. */
function superpositionQasm(count: number): string {
  const lines = ['OPENQASM 2.0;', 'include "qelib1.inc";', `qreg q[${count}];`, `creg c[${count}];`];
  for (let index = 0; index < count; index += 1) lines.push(`h q[${index}];`);
  for (let index = 0; index < count; index += 1) lines.push(`measure q[${index}] -> c[${index}];`);
  return lines.join("\n");
}
