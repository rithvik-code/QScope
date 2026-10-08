/**
 * Build — the circuit IDE.
 *
 * The editor is a thin, honest layer over the engine: it edits an operation list
 * locally and then asks the backend for the authoritative document (resources,
 * depth, layer count, diagram, QASM).  Nothing is estimated client-side, so the
 * numbers in the header are the same ones a run will use.
 */

import { useMemo, useRef, useState } from "react";
import { FieldGuide } from "../components/Guide";
import { api } from "../lib/api";
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

export function BuildMode({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const { meta, document: circuit, selection, loading, errors, loadAlgorithm, loadQasm, resetCircuit, editCircuit, setQubitCount, setSource, planRun, runPanic, note } =
    useStore();
  const [selected, setSelected] = useState<number | null>(null);
  const [view, setView] = useState<"diagram" | "qasm">("diagram");
  const [qubits, setQubits] = useState(3);
  const guideRef = useRef<HTMLDivElement | null>(null);
  const [qasmInput, setQasmInput] = useState("");
  const [pendingGate, setPendingGate] = useState<string | null>(null);

  const selectedOperation = useMemo(
    () => (circuit && selected !== null ? circuit.operations[selected] ?? null : null),
    [circuit, selected],
  );

  const addGate = async (name: string, params: number[] | undefined) => {
    if (!circuit) return;
    const wires = Array.from({ length: name === "TOFFOLI" ? 3 : 2 }, (_, index) => index).filter((wire) => wire < circuit.num_qubits);
    if (name === "measure" || name === "reset" || name === "barrier") {
      await editCircuit((operations) => {
        operations.push({
          name,
          targets: [0],
          params: [],
          controls: [],
          classical_targets: name === "measure" ? [0] : [],
          kind: name === "measure" || name === "reset" || name === "barrier" ? name : "gate",
          label: "",
          opid: `local-${Date.now()}-${operations.length}`,
        } as CircuitOperation);
        return operations;
      });
      note("edit", `added ${name} on q0`);

      return;
    }
    const arity = GATE_GROUPS.flatMap((group) => group.gates).find((gate) => gate.name === name)?.arity ?? 1;
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
      <div className="grid gap-4 xl:grid-cols-[300px_1fr]">
        {/* -------------------------------------------------- gate palette */}
        <div className="space-y-3">
          <Panel title="Sources" subtitle="Start from an algorithm, a template, QASM or an empty register." dense>
            <div className="space-y-2.5">
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

          <Panel title="Gate palette" subtitle="Click a gate to append it to q0…q{n-1}." dense>
            <div className="space-y-3">
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
            <Panel title="Operation list" subtitle="Select to edit parameters or reorder." dense>
              <div className="max-h-[300px] space-y-1 overflow-y-auto pr-1">
                {!circuit?.operations.length && <p className="text-[11px] text-[var(--c-faint)]">No operations yet.</p>}
                {circuit?.operations.map((operation, index) => (
                  <div
                    key={operation.opid ?? index}
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
