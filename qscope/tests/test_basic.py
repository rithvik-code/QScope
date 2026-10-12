import numpy as np
from qscope import Circuit, grover, shor, qft_circuit

def test_bell():
    p = Circuit(2).h(0).cx(0, 1).run().probabilities()
    assert np.allclose(p, [.5, 0, 0, .5])

def test_qft_matches_fft():
    n = 4; c = Circuit(n); c.x(1)  # basis state |0100> = 4
    for op in qft_circuit(n).ops: c.add(*op)
    e = np.zeros(2 ** n); e[4] = 1
    assert np.allclose(c.run().amplitudes(), np.fft.ifft(e) * np.sqrt(2 ** n))

def test_grover():
    assert grover(8, [77])["success_probability"] > 0.99

def test_shor():
    assert shor(15, seed=1)["factors"] == (3, 5)
    assert shor(21, seed=2)["factors"] == (3, 7)
