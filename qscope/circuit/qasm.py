"""OpenQASM 2.0 / 3.0 interop.

Conventions QScope has to be explicit about
------------------------------------------
* **``rz``** — qelib1's ``rz(θ)`` is ``diag(1, e^{iθ})``, which is QScope's ``P(θ)``,
  not the ``Rz(θ) = diag(e^{-iθ/2}, e^{iθ/2})`` used elsewhere.  We map
  ``RZ → rz`` on export and ``rz → RZ`` on import so a QScope round trip is
  exact; the two definitions differ only by a global phase, which cannot affect
  measurement statistics.
* **``sx``** — QASM2 has no square root of X, so we emit a declaration whose body
  is ``u3(pi/2,-pi/2,pi/2)``.  That equals ``√X`` up to a global phase.
* Gates with no QASM2 primitive (``CH``, ``CY``, ``iSWAP``, ``Rxx/Ryy/Rzz/Rzx``,
  ``CSWAP``, ``√X``) are emitted as ``gate`` declarations with exact bodies, so the
  exported file is self-contained and re-imports to an equivalent circuit.

Import expands gate definitions recursively down to primitives, which means files
produced by Qiskit/Quil-style toolchains import into QScope's own gate set.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Iterable

from qscope.circuit.circuit import Circuit, Condition, Operation

# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

TO_QASM2: dict[str, tuple[str, int]] = {
    "I": ("id", 0),
    "X": ("x", 0),
    "Y": ("y", 0),
    "Z": ("z", 0),
    "H": ("h", 0),
    "S": ("s", 0),
    "SDG": ("sdg", 0),
    "T": ("t", 0),
    "TDG": ("tdg", 0),
    "RX": ("rx", 1),
    "RY": ("ry", 1),
    "RZ": ("rz", 1),
    "P": ("u1", 1),
    "U2": ("u2", 2),
    "U3": ("u3", 3),
    "CNOT": ("cx", 0),
    "CX": ("cx", 0),
    "CZ": ("cz", 0),
    "SWAP": ("swap", 0),
    "TOFFOLI": ("ccx", 0),
    "CCX": ("ccx", 0),
}
"""Gates with a qelib1 primitive.  Value is ``(qasm_name, num_params)``."""

FROM_QASM: dict[str, str] = {
    "id": "I",
    "u": "U3",
    "U": "U3",
    "u3": "U3",
    "u2": "U2",
    "u1": "P",
    "p": "P",
    "x": "X",
    "y": "Y",
    "z": "Z",
    "h": "H",
    "s": "S",
    "sdg": "SDG",
    "t": "T",
    "tdg": "TDG",
    "sx": "SX",
    "sxdg": "SXDG",
    "rx": "RX",
    "ry": "RY",
    "rz": "RZ",
    "cx": "CNOT",
    "CX": "CNOT",
    "cz": "CZ",
    "cy": "CY",
    "ch": "CH",
    "swap": "SWAP",
    "iswap": "ISWAP",
    "ccx": "TOFFOLI",
    "cswap": "CSWAP",
    "mcx": "MCX",
    # stdgates.inc (QASM3) additions so those names import directly too
    "rxx": "RXX",
    "ryy": "RYY",
    "rzz": "RZZ",
    "rzx": "RZX",
    "iswapdg": "ISWAPDG",
    "sxdg": "SXDG",
    "ccz": "CCZ",
}

DECLARATIONS: dict[str, str] = {
    "rz": "gate rz(theta) a { u1(theta) a; }",
    "rzz": "gate rzz(theta) a,b { cx a,b; rz(theta) b; cx a,b; }",
    "rxx": "gate rxx(theta) a,b { h a; h b; rzz(theta) a,b; h a; h b; }",
    "ryy": "gate ryy(theta) a,b { sdg a; sdg b; rxx(theta) a,b; s a; s b; }",
    "rzx": "gate rzx(theta) a,b { h b; rzz(theta) a,b; h b; }",
    "cy": "gate cy a,b { sdg b; cx a,b; s b; }",
    # H = Ry(pi/4) Z Ry(-pi/4), so C(H) = Ry(pi/4)(t) CZ Ry(-pi/4)(t) — written in
    # QASM order that means the last line is applied first.
    "ch": "gate ch a,b { ry(-pi/4) b; cz a,b; ry(pi/4) b; }",
    "sx": "gate sx a { u3(pi/2,-pi/2,pi/2) a; }",
    "sxdg": "gate sxdg a { u3(-pi/2,-pi/2,pi/2) a; }",
    "iswap": "gate iswap a,b { cz a,b; cx a,b; cx b,a; cx a,b; s a; s b; }",
    "iswapdg": "gate iswapdg a,b { sdg a; sdg b; cx a,b; cx b,a; cx a,b; cz a,b; }",
    "cswap": "gate cswap c,a,b { ccx c,a,b; ccx c,b,a; ccx c,a,b; }",
}
"""Exact bodies for gates QASM2 does not provide (order: dependencies first)."""

DECLARATION_ORDER = ["rz", "rzz", "rxx", "ryy", "rzx", "cy", "ch", "sx", "sxdg", "iswap", "iswapdg", "cswap"]

DECLARATION_DEPS: dict[str, list[str]] = {
    "rz": [],
    "rzz": ["rz"],
    "rxx": ["rzz"],
    "ryy": ["rxx"],
    "rzx": ["rzz"],
    "cy": [],
    "ch": [],
    "sx": [],
    "sxdg": [],
    "iswap": [],
    "iswapdg": [],
    "cswap": [],
}
"""Which declarations a declaration body relies on (bodies are nested)."""

QELIB1_PROVIDED = {"rz"}
"""Names qelib1.inc already defines; re-emitting them would shadow the standard."""

NEEDS_DECLARATION: dict[str, str] = {
    "SX": "sx",
    "SXDG": "sxdg",
    "CY": "cy",
    "CH": "ch",
    "ISWAP": "iswap",
    "ISWAPDG": "iswapdg",
    "CSWAP": "cswap",
    "RXX": "rxx",
    "RYY": "ryy",
    "RZZ": "rzz",
    "RZX": "rzx",
}

QASM3_PRIMITIVES = {"I", "X", "Y", "Z", "H", "S", "SDG", "T", "TDG", "SX", "SXDG", "RX", "RY", "RZ", "P", "U2", "U3", "CNOT", "CZ", "CY", "CH", "SWAP", "ISWAP", "TOFFOLI", "CCZ", "CSWAP"}


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def _fmt_param(value: float) -> str:
    """Render a parameter as a QASM expression (multiples of pi where exact)."""
    if abs(value) < 1e-15:
        return "0"
    ratio = value / 3.141592653589793
    for denom in (1, 2, 3, 4, 6, 8):
        numeric = ratio * denom
        if abs(numeric - round(numeric)) < 1e-12 and round(numeric) != 0:
            num = int(round(numeric))
            sign = "-" if num < 0 else ""
            num = abs(num)
            head = "" if num == 1 else f"{num}*"
            tail = "pi" if denom == 1 else f"pi/{denom}"
            return f"{sign}{head}{tail}"
    return f"{value:.12g}"


def to_qasm(circuit: Circuit, *, version: str = "2.0") -> str:
    """Serialise a circuit to OpenQASM text.

    ``version="3.0"`` emits native ``stdgates`` and the ``c[i] = measure q[j];``
    form.  Both outputs re-import into QScope losslessly (up to the global-phase
    caveats documented at module level).
    """
    if version not in ("2.0", "3.0"):
        raise ValueError("version must be '2.0' or '3.0'")
    lines: list[str] = [f"OPENQASM {version};"]
    lines.append('include "qelib1.inc";' if version == "2.0" else 'include "stdgates.inc";')
    lines.append("")
    lines.append(f"// {circuit.name}: {circuit.num_qubits} qubits, {len(circuit)} operations")
    if circuit.description:
        for chunk in circuit.description.strip().splitlines():
            lines.append(f"// {chunk}")
    lines.append("")
    lines.append(f"qreg q[{circuit.num_qubits}];")
    if circuit.num_clbits:
        lines.append(f"creg c[{circuit.num_clbits}];")
    lines.append("")

    if version == "2.0":
        emitted = [DECLARATIONS[key] for key in required_declarations(circuit)]
    else:
        # QASM3's stdgates.inc already provides ``sx``/``cy``/``ch``/``rzz``/``rxx``/
        # ``ryy``/``iswap``/``cswap``; only these two names still need a body.
        stdgates_missing = {"rzx", "iswapdg"}
        used = {
            NEEDS_DECLARATION[op.name]
            for op in circuit.operations
            if op.kind == "gate" and op.name in NEEDS_DECLARATION
        }
        emitted = [DECLARATIONS[k] for k in DECLARATION_ORDER if k in used & stdgates_missing]
    if emitted:
        lines.extend(emitted)
        lines.append("")

    for op in circuit.operations:
        lines.append(_op_to_qasm(op, circuit, version))
    return "\n".join(lines) + "\n"


def _op_to_qasm(op: Operation, circuit: Circuit, version: str) -> str:
    qargs = [f"q[{t}]" for t in op.targets]
    prefix = ""
    if op.condition is not None:
        clbit = circuit.clbits.label(op.condition.clbit)
        prefix = f"if (c=={op.condition.value}) "
    if op.kind == "barrier":
        wires = ",".join(f"q[{q}]" for q in op.targets)
        return f"barrier {wires};"
    if op.kind == "reset":
        return f"reset q[{op.targets[0]}];"
    if op.kind == "delay":
        duration = op.params[0] if op.params else 0.0
        return f"// delay {duration:g} on q[{op.targets[0]}] (QASM has no native delay)"
    if op.kind == "measure":
        if version == "3.0":
            return f"c[{op.classical_targets[0]}] = measure q[{op.targets[0]}];"
        return f"measure q[{op.targets[0]}] -> c[{op.classical_targets[0]}];"

    name = op.name
    if op.controls:
        if op.arity == 1 and len(op.controls) == 1 and not op.params:
            controls = [f"q[{c}]" for c in op.controls]
            if name == "X":
                return f"{prefix}cx {','.join(controls + qargs)};"
            if name == "Z":
                return f"{prefix}cz {','.join(controls + qargs)};"
            raise NotImplementedError(
                f"QASM export cannot express the controlled-{name} gate; "
                "decompose it or export the project as JSON"
            )
        raise NotImplementedError(
            "QASM export supports at most one explicit control on a single-qubit gate"
        )

    if version == "3.0" and name in QASM3_PRIMITIVES:
        qasm_name = TO_QASM2.get(name, (name.lower(), len(op.params)))[0]
        if len(op.params) == 0:
            return f"{prefix}{qasm_name} {','.join(qargs)};"
        args = ",".join(_fmt_param(p) for p in op.params)
        return f"{prefix}{qasm_name}({args}) {','.join(qargs)};"

    if name in TO_QASM2:
        qasm_name, arity = TO_QASM2[name]
        if arity and len(op.params) != arity:
            raise ValueError(f"gate {name} needs {arity} parameter(s) for QASM export")
        if arity:
            args = ",".join(_fmt_param(p) for p in op.params)
            return f"{prefix}{qasm_name}({args}) {','.join(qargs)};"
        return f"{prefix}{qasm_name} {','.join(qargs)};"

    if name in NEEDS_DECLARATION:
        qasm_name = NEEDS_DECLARATION[name]
        if op.params:
            args = ",".join(_fmt_param(p) for p in op.params)
            return f"{prefix}{qasm_name}({args}) {','.join(qargs)};"
        return f"{prefix}{qasm_name} {','.join(qargs)};"

    if name == "MCX":
        n_controls = op.arity - 1
        if n_controls == 2:
            return f"{prefix}ccx {','.join(qargs)};"
        raise NotImplementedError(
            "QASM 2.0 has no ancilla-free decomposition for a "
            f"{n_controls}-controlled X; export this circuit as JSON instead"
        )
    if name == "CCZ":
        # CCZ = H(target) CCX H(target), exact.
        last = qargs[-1]
        return (
            f"{prefix}h {last};\n"
            f"{prefix}ccx {','.join(qargs)};\n"
            f"{prefix}h {last};"
        )

    raise NotImplementedError(
        f"gate {name} has no OpenQASM mapping; QScope can still export this circuit as JSON"
    )


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

_EXPR_ALLOWED = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Mod,
    ast.Call,
    ast.Load,
)


def eval_expr(text: str, env: dict[str, float]) -> float:
    """Evaluate a QASM parameter expression without ``eval``.

    Only arithmetic over ``pi`` and the enclosing gate's parameters is
    permitted, so an untrusted file cannot execute code.
    """
    text = text.strip()
    if not text:
        return 0.0
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"cannot parse QASM expression {text!r}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _EXPR_ALLOWED):
            raise ValueError(f"unsupported construct in QASM expression {text!r}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in {"sin", "cos", "tan", "sqrt", "exp", "ln", "log"}:
                raise ValueError(f"unsupported function in QASM expression {text!r}")
    import math

    local_env = {
        "pi": math.pi,
        "PI": math.pi,
        "tau": 2 * math.pi,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "sqrt": math.sqrt,
        "exp": math.exp,
        "ln": math.log,
        "log": math.log,
        **env,
    }
    return float(eval(compile(tree, "<qasm>", "eval"), {"__builtins__": {}}, local_env))  # noqa: S307 - AST-validated


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    out: list[str] = []
    for line in text.splitlines():
        line = line.split("//")[0]
        out.append(line)
    return "\n".join(out)


def _split_statements(text: str) -> list[str]:
    """Split on ``;`` and ``{``/``}`` boundaries while keeping definitions intact."""
    statements: list[str] = []
    buf = ""
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
            buf += ch
        elif ch == "}":
            depth -= 1
            buf += ch
            if depth == 0:
                statements.append(buf.strip())
                buf = ""
        elif ch == ";" and depth == 0:
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        statements.append(buf.strip())
    return [s for s in statements if s]


class _GateDef:
    __slots__ = ("name", "params", "args", "body")

    def __init__(self, name: str, params: list[str], args: list[str], body: list[str]) -> None:
        self.name = name
        self.params = params
        self.args = args
        self.body = body


_RE_DEF = re.compile(
    r"^\s*gate\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(([^)]*)\))?\s*([A-Za-z0-9_,\s]*?)\s*\{(.*)\}\s*$",
    re.DOTALL,
)


def from_qasm(text: str) -> Circuit:
    """Parse OpenQASM 2.0 or 3.0 text into a :class:`Circuit`.

    Gate bodies are expanded recursively to primitives, so the resulting circuit
    is expressed purely in QScope's native gate set.
    """
    clean = _strip_comments(text)
    if "OPENQASM" not in clean:
        raise ValueError("not an OpenQASM file (missing OPENQASM header)")
    statements = _split_statements(clean)

    qregs: list[tuple[str, int]] = []
    cregs: list[tuple[str, int]] = []
    definitions: dict[str, _GateDef] = {}
    body_statements: list[str] = []

    for stmt in statements:
        s = stmt.strip()
        if not s or s.startswith("OPENQASM"):
            continue
        if s.startswith("include") or s.startswith("opaque"):
            continue
        if s.startswith("qreg"):
            name, size = _parse_reg(s)
            qregs.append((name, size))
            continue
        if s.startswith("creg"):
            name, size = _parse_reg(s)
            cregs.append((name, size))
            continue
        match = _RE_DEF.match(s)
        if match:
            body = _split_statements(match.group(4))
            definitions[match.group(1)] = _GateDef(
                match.group(1),
                [p.strip() for p in (match.group(2) or "").split(",") if p.strip()],
                [a.strip() for a in (match.group(3) or "").split(",") if a.strip()],
                body,
            )
            continue
        body_statements.append(s)

    if not qregs:
        raise ValueError("QASM file declares no quantum register")
    total_qubits = sum(size for _, size in qregs)
    total_clbits = sum(size for _, size in cregs)
    q_offsets = _offsets(qregs)
    c_offsets = _offsets(cregs)

    circuit = Circuit(
        total_qubits,
        total_clbits,
        name="imported",
        metadata={"source": "qasm"},
    )

    for stmt in body_statements:
        _emit_statement(circuit, stmt, definitions, q_offsets, c_offsets, {}, depth=0)
    return circuit


def _offsets(regs: list[tuple[str, int]]) -> dict[str, int]:
    out: dict[str, int] = {}
    offset = 0
    for name, size in regs:
        out[name] = offset
        offset += size
    return out


def _parse_reg(stmt: str) -> tuple[str, int]:
    match = re.match(r"^\s*(qreg|creg)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(\d+)\s*\]", stmt)
    if not match:
        raise ValueError(f"cannot parse register declaration {stmt!r}")
    return match.group(2), int(match.group(3))


def _emit_statement(
    circuit: Circuit,
    stmt: str,
    definitions: dict[str, _GateDef],
    q_offsets: dict[str, int],
    c_offsets: dict[str, int],
    env: dict[str, float],
    depth: int,
    wire_map: dict[str, int] | None = None,
) -> None:
    if depth > 64:
        raise ValueError("QASM gate definition recursion too deep (cyclic definitions?)")
    s = stmt.strip()
    if not s:
        return
    condition: Condition | None = None
    if s.startswith("if"):
        match = re.match(r"^if\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(\d+)\s*\]\s*==\s*(\d+)\s*\)\s*(.+)$", s)
        if not match:
            raise ValueError(f"unsupported if-condition {s!r}")
        condition = Condition(
            clbit=c_offsets.get(match.group(1), 0) + int(match.group(2)),
            value=int(match.group(3)),
        )
        s = match.group(4).strip()

    if s.startswith("barrier"):
        wires = _parse_qargs(s[len("barrier") :], q_offsets, wire_map)
        circuit.barrier(wires)
        return
    if s.startswith("reset"):
        wires = _parse_qargs(s[len("reset") :], q_offsets, wire_map)
        for q in wires:
            circuit.reset(q)
        return
    if s.startswith("measure"):
        match = re.match(r"^measure\s+(.+?)\s*->\s*(.+)$", s)
        if not match:
            raise ValueError(f"cannot parse measurement {s!r}")
        q = _parse_qargs(match.group(1), q_offsets, wire_map)[0]
        c = _parse_qargs(match.group(2), c_offsets)[0] if c_offsets else 0
        circuit.measure(q, c)
        return
    # QASM 3 style: c[0] = measure q[0];
    match3 = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(\d+)\s*\]\s*=\s*measure\s+([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(\d+)\s*\]$", s)
    if match3:
        c = c_offsets.get(match3.group(1), 0) + int(match3.group(2))
        q = q_offsets.get(match3.group(3), 0) + int(match3.group(4))
        circuit.measure(q, c)
        return
    if "=" in s and "measure" not in s:
        raise ValueError(f"unsupported QASM statement {s!r}")

    # gate call: name(params) qargs
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(([^)]*)\))?\s*(.*)$", s)
    if not match:
        raise ValueError(f"cannot parse QASM statement {s!r}")
    name, args, qarg_text = match.group(1), match.group(2), match.group(3)
    params = [eval_expr(part, env) for part in _split_args(args)] if args and args.strip() else []
    qargs = _parse_qargs(qarg_text, q_offsets, wire_map)

    if name in definitions:
        definition = definitions[name]
        if len(qargs) != len(definition.args):
            raise ValueError(
                f"gate {name} expects {len(definition.args)} qubit arguments, got {len(qargs)}"
            )
        if len(params) != len(definition.params):
            raise ValueError(
                f"gate {name} expects {len(definition.params)} parameter(s), got {len(params)}"
            )
        inner_env = dict(zip(definition.params, params))
        inner_wires = dict(zip(definition.args, qargs))
        for body_stmt in definition.body:
            _emit_statement(
                circuit,
                body_stmt,
                definitions,
                q_offsets,
                c_offsets,
                inner_env,
                depth + 1,
                inner_wires,
            )
        return

    canonical = FROM_QASM.get(name) or FROM_QASM.get(name.lower())
    if canonical is None:
        raise ValueError(
            f"unknown gate {name!r}: it is neither a QASM primitive QScope knows "
            "nor defined in this file"
        )
    op = Operation(
        name=canonical,
        targets=list(qargs),
        params=list(params),
        condition=condition,
        kind="gate",
    )
    if canonical == "MCX" and len(qargs) >= 2:
        op.targets = list(qargs)
        op.name = "MCX"
    circuit.append(op)


def _split_args(text: str) -> list[str]:
    if not text:
        return []
    parts: list[str] = []
    depth = 0
    buf = ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _parse_qargs(
    text: str,
    offsets: dict[str, int],
    wire_map: dict[str, int] | None = None,
) -> list[int]:
    """Resolve qubit arguments: ``q[3]``, or a gate-definition argument name."""
    wire_map = wire_map or {}
    out: list[int] = []
    for token in _split_args(text):
        token = token.strip()
        if not token:
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(\d+)\s*\]$", token)
        if match:
            reg, idx = match.group(1), int(match.group(2))
            if reg not in offsets:
                raise ValueError(f"unknown register {reg!r} in {text!r}")
            out.append(offsets[reg] + idx)
        elif token in wire_map:
            out.append(wire_map[token])
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", token):
            # A whole-register reference such as ``barrier q;`` — QScope always
            # writes explicit bit indices, so refuse rather than guess a range.
            raise ValueError(
                f"whole-register argument {token!r} is not supported; list individual bits"
            )
        else:
            raise ValueError(f"cannot parse qubit argument {token!r}")
    return out


def required_declarations(circuit: Circuit) -> list[str]:
    """Declaration keys a circuit needs, including nested dependencies.

    ``RZX`` needs ``rzz``, which needs ``rz`` — emitting only the directly used
    declaration would produce a file that cannot be compiled.
    """
    wanted = {
        NEEDS_DECLARATION[op.name]
        for op in circuit.operations
        if op.kind == "gate" and op.name in NEEDS_DECLARATION
    }
    closure: set[str] = set()
    stack = list(wanted)
    while stack:
        key = stack.pop()
        if key in closure:
            continue
        closure.add(key)
        stack.extend(DECLARATION_DEPS.get(key, []))
    return [k for k in DECLARATION_ORDER if k in closure and k not in QELIB1_PROVIDED]


def expand_definitions_needed(circuit: Circuit) -> list[str]:
    """QASM2 declaration text a circuit requires (used by tests and exporters)."""
    return [DECLARATIONS[key] for key in required_declarations(circuit)]


def iter_ops(circuit: Circuit) -> Iterable[Operation]:
    return iter(circuit.operations)


__all__ = [
    "DECLARATIONS",
    "DECLARATION_ORDER",
    "FROM_QASM",
    "NEEDS_DECLARATION",
    "TO_QASM2",
    "DECLARATION_DEPS",
    "QELIB1_PROVIDED",
    "eval_expr",
    "expand_definitions_needed",
    "from_qasm",
    "required_declarations",
    "to_qasm",
]
