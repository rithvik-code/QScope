# QScope ⚛️
A quantum circuit **simulator** that runs on a normal laptop (NumPy; optional GPU via CuPy).

> It does NOT make your laptop a quantum computer. Simulating n qubits costs 2^n memory/time.
> QScope is for learning, debugging and benchmarking quantum programs (up to ~25-28 qubits).

## Run
    pip install -r requirements.txt
    python -m qscope bell
    python -m qscope grover 12 --marked 777
    python -m qscope shor 21
    python -m qscope bench --max-qubits 22
    python -m pytest tests

## Use as a library
    from qscope import Circuit
    c = Circuit(3).h(0).cx(0, 1).cx(1, 2)   # GHZ state
    print(c.run().sample(1000))

## Roadmap (from the design notes)
Circuit IDE (web UI) · Bloch/state-vector visualizer · noise + error correction ·
AI circuit explainer · full CPU vs GPU benchmark dashboard
