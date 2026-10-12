"""State-vector engine. Qubit 0 is the most significant bit of the basis index.
Memory is 16 bytes * 2^n (complex128): 25 qubits = 512 MB, 30 qubits = 16 GB."""
import numpy as np
from collections import Counter

try:
    import cupy as cp
except Exception:  # no GPU / no cupy
    cp = None

_s = 1 / np.sqrt(2)
gates = {
    "I": np.eye(2, dtype=complex),
    "H": np.array([[_s, _s], [_s, -_s]], dtype=complex),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
    "S": np.array([[1, 0], [0, 1j]], dtype=complex),
    "T": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
    "SWAP": np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex),
}

def phase(phi):
    return np.array([[1, 0], [0, np.exp(1j * phi)]], dtype=complex)

def rz(theta):
    return np.array([[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]], dtype=complex)

def controlled(U, n_controls=1):
    """Controls come first in the qubit list, targets last."""
    d = U.shape[0]
    M = np.eye(d * 2 ** n_controls, dtype=complex)
    M[-d:, -d:] = U
    return M

def gpu_available():
    if cp is None:
        return False
    try:
        return cp.cuda.runtime.getDeviceCount() > 0
    except Exception:
        return False

class StateVector:
    def __init__(self, n, backend="cpu", dtype=np.complex128):
        if backend == "gpu":
            if not gpu_available():
                raise RuntimeError("GPU backend needs an NVIDIA GPU + cupy installed")
            self.xp = cp
        else:
            self.xp = np
        self.n, self.backend = n, backend
        self.psi = self.xp.zeros((2,) * n, dtype=dtype)
        self.psi[(0,) * n] = 1

    def apply(self, U, targets):
        xp, k = self.xp, len(targets)
        U = xp.asarray(U, dtype=self.psi.dtype).reshape((2,) * (2 * k))
        out = xp.tensordot(U, self.psi, axes=(list(range(k, 2 * k)), list(targets)))
        self.psi = xp.moveaxis(out, list(range(k)), list(targets))

    def apply_diagonal(self, phases):
        """Multiply amplitudes by a length-2^n vector (used for oracles)."""
        self.psi = self.psi * self.xp.asarray(phases).reshape((2,) * self.n)

    def probabilities(self):
        p = self.xp.abs(self.psi.reshape(-1)) ** 2
        return p.get() if self.backend == "gpu" else p

    def amplitudes(self):
        a = self.psi.reshape(-1)
        return a.get() if self.backend == "gpu" else a

    def sample(self, shots=1024, seed=None):
        rng = np.random.default_rng(seed)
        p = self.probabilities()
        idx = rng.choice(len(p), size=shots, p=p / p.sum())
        return Counter(format(i, f"0{self.n}b") for i in idx)

    def bloch(self, qubit):
        """Bloch vector (x, y, z) of one qubit (reduced density matrix)."""
        psi = np.moveaxis(self.amplitudes().reshape((2,) * self.n), qubit, 0).reshape(2, -1)
        rho = psi @ psi.conj().T
        return (2 * rho[0, 1].real, -2 * rho[0, 1].imag, (rho[0, 0] - rho[1, 1]).real)
