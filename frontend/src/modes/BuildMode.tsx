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
      <FieldGuide
        modeName="Build"            onDismiss={() => {}}
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

      <div className="space-y-3">
        <Panel title="Sources" subtitle="Start from an algorithm, a template, QASM or an empty register." dense>