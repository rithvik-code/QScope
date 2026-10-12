import numpy as np
from .simulator import StateVector, gates, controlled, phase, rz

class Circuit:
    def __init__(self, n):
        self.n, self.ops = n, []

    def add(self, name, matrix, qubits):
        self.ops.append((name, matrix, list(qubits)))
        return self

    def h(self, q): return self.add("H", gates["H"], [q])
    def x(self, q): return self.add("X", gates["X"], [q])
    def y(self, q): return self.add("Y", gates["Y"], [q])
    def z(self, q): return self.add("Z", gates["Z"], [q])
    def s(self, q): return self.add("S", gates["S"], [q])
    def t(self, q): return self.add("T", gates["T"], [q])
    def rz(self, th, q): return self.add(f"RZ({th:.2f})", rz(th), [q])
    def p(self, phi, q): return self.add(f"P({phi:.2f})", phase(phi), [q])
    def cx(self, c, t): return self.add("CX", controlled(gates["X"]), [c, t])
    def cz(self, c, t): return self.add("CZ", controlled(gates["Z"]), [c, t])
    def cp(self, phi, c, t): return self.add(f"CP({phi:.2f})", controlled(phase(phi)), [c, t])
    def ccx(self, a, b, t): return self.add("CCX", controlled(gates["X"], 2), [a, b, t])
    def swap(self, a, b): return self.add("SWAP", gates["SWAP"], [a, b])

    def run(self, backend="cpu", state=None):
        st = state or StateVector(self.n, backend)
        for _, m, q in self.ops:
            st.apply(m, q)
        return st

    def draw(self):
        rows = [f"q{i}: " for i in range(self.n)]
        for name, _, qs in self.ops:
            w = len(name) + 2
            for i in range(self.n):
                rows[i] += (f"[{name}]" if i == qs[-1] else
                            ("-●" + "-" * (w - 2) if i in qs else "-" * w)).ljust(w, "-")
        return "\n".join(rows)
