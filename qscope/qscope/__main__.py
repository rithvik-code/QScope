import argparse
from . import grover, shor, qft_circuit, Circuit, bench

def main():
    ap = argparse.ArgumentParser(prog="qscope", description="QScope: quantum circuit simulator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grover"); g.add_argument("n", type=int); g.add_argument("--marked", type=int, nargs="+", default=[3]); g.add_argument("--gpu", action="store_true")
    s = sub.add_parser("shor"); s.add_argument("N", type=int)
    sub.add_parser("bell")
    q = sub.add_parser("qft"); q.add_argument("n", type=int)
    b = sub.add_parser("bench"); b.add_argument("--max-qubits", type=int, default=20)
    a = ap.parse_args()
    if a.cmd == "grover":
        print(grover(a.n, a.marked, "gpu" if a.gpu else "cpu"))
    elif a.cmd == "shor":
        print(shor(a.N))
    elif a.cmd == "bell":
        c = Circuit(2).h(0).cx(0, 1); print(c.draw()); print(c.run().sample(1000))
    elif a.cmd == "qft":
        c = qft_circuit(a.n); print(c.draw())
    elif a.cmd == "bench":
        bench.run(a.max_qubits)

main()
