import time, numpy as np
from .algorithms import qft_circuit
from .simulator import gpu_available

def run(max_qubits=20, start=8, step=2):
    backends = ["cpu"] + (["gpu"] if gpu_available() else [])
    print(f"{'qubits':>6} {'state MB':>10} " + " ".join(f"{b+' sec':>10}" for b in backends))
    for n in range(start, max_qubits + 1, step):
        row = []
        for b in backends:
            c = qft_circuit(n); t0 = time.perf_counter(); c.run(b); row.append(time.perf_counter() - t0)
        print(f"{n:>6} {16 * 2**n / 1e6:>10.1f} " + " ".join(f"{x:>10.4f}" for x in row))
    if len(backends) == 1:
        print("(no GPU/cupy detected -> CPU only)")
    print("Each +1 qubit doubles memory and (at least) doubles time. That wall is the point.")
