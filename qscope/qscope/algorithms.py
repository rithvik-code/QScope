import math, random
import numpy as np
from fractions import Fraction
from .simulator import StateVector, gates
from .circuit import Circuit

def qft_circuit(n):
    c = Circuit(n)
    for j in range(n):
        c.h(j)
        for k in range(j + 1, n):
            c.cp(math.pi / 2 ** (k - j), k, j)
    for i in range(n // 2):
        c.swap(i, n - 1 - i)
    return c

def grover(n, marked, backend="cpu", shots=1024, seed=None):
    """Grover search over 2^n items. `marked` = list of integers."""
    marked = list(marked)
    N = 2 ** n
    iters = max(1, int(math.floor(math.pi / 4 * math.sqrt(N / len(marked)))))
    st = StateVector(n, backend)
    H = gates["H"]
    for q in range(n): st.apply(H, [q])
    oracle = np.ones(N); oracle[marked] = -1
    flip0 = np.ones(N); flip0[0] = -1
    for _ in range(iters):
        st.apply_diagonal(oracle)                      # oracle: phase-flip marked states
        for q in range(n): st.apply(H, [q])            # diffusion: H^n (2|0><0|-I) H^n
        st.apply_diagonal(flip0)
        for q in range(n): st.apply(H, [q])
        st.psi = -st.psi
    p = st.probabilities()
    return {"iterations": iters, "success_probability": float(sum(p[m] for m in marked)),
            "counts": st.sample(shots, seed).most_common(5),
            "classical_expected_queries": N // 2, "quantum_queries": iters}

def shor(N, a=None, max_tries=12, seed=None):
    """Shor via simulated phase estimation. NOTE: the modular-exponentiation register is
    built directly (not decomposed into gates) -- that part is the expensive one on
    real hardware. Works for small N (<~150)."""
    rnd = random.Random(seed)
    if N % 2 == 0: return {"factors": (2, N // 2), "note": "even"}
    t = 2 * N.bit_length(); M = 2 ** t
    for attempt in range(max_tries):
        a_ = a or rnd.randrange(2, N)
        g = math.gcd(a_, N)
        if g > 1: return {"factors": (g, N // g), "a": a_, "note": "lucky gcd"}
        vals = np.array([pow(a_, x, N) for x in range(M)])
        psi = np.zeros((M, N), dtype=complex)
        psi[np.arange(M), vals] = 1 / math.sqrt(M)
        psi = np.fft.fft(psi, axis=0, norm="ortho")            # QFT on counting register
        probs = (np.abs(psi) ** 2).sum(axis=1)
        k = int(np.random.default_rng(rnd.randrange(10**9)).choice(M, p=probs / probs.sum()))
        r0 = Fraction(k, M).limit_denominator(N).denominator
        for r in (r0, 2 * r0, 3 * r0):
            if r > 0 and pow(a_, r, N) == 1:
                if r % 2 == 0 and pow(a_, r // 2, N) != N - 1:
                    f = math.gcd(pow(a_, r // 2, N) - 1, N)
                    if 1 < f < N:
                        return {"factors": tuple(sorted((f, N // f))), "a": a_, "period": r,
                                "counting_qubits": t, "attempts": attempt + 1}
                break
        if a: break
    return {"factors": None, "note": "no factor found; retry"}
