# QScope: A Local-First, Resource-Aware Quantum Circuit Simulation and Research Workspace

**[Author name]**  
**[Department, Institution, City, Country]**  
**[Email address]**

**Abstract—** Quantum-circuit experimentation is commonly split across programming frameworks, simulators, notebooks, visualizers, and result logs. This fragmentation can make it difficult for new users to connect a circuit edit to its computational cost, intermediate quantum state, and final measurement. This paper presents QScope, an open-source, local-first quantum-circuit simulation and research workspace designed to connect those steps in one reproducible workflow. QScope combines a Python/NumPy gate-model engine with a browser interface for circuit construction, OpenQASM-oriented interchange, ideal and noisy simulation, gate-by-gate tracing, analysis, optimization, and experiment history. Its execution planner selects or validates a simulator representation and estimates working memory before execution. For batch experiments, a memory-bounded scheduler runs independent circuits in concurrent waves while preserving result order and respecting a shared estimated peak-memory budget. QScope records seeds, shots, backend, noise settings, timing, memory, and execution mode with results; its optimizer reports verification outcomes and reverts unverified rewrites. A five-trial local benchmark using six-layer circuits from 6 to 14 qubits measured median runtimes from 6.69 ms to 229.93 ms on a 16-logical-CPU Windows system. These measurements illustrate the machine dependence and rapid growth of classical simulation; they do not establish hardware performance or quantum advantage. The full automated test suite completed successfully. QScope’s contribution is an integrated, inspectable workflow—not a new quantum algorithm or a claim to outperform specialized simulators.

**Keywords—** quantum circuit simulation, state vector, density matrix, quantum trajectory, circuit debugging, reproducibility, memory-aware scheduling, quantum software.

<!-- TWO_COLUMN -->

## I. INTRODUCTION

Quantum programs are specified as sequences of operations on qubits, but understanding a program usually requires more than obtaining a final bit string. A researcher or learner may need to inspect circuit structure, intermediate states, measurement distributions, noise assumptions, resource consumption, and the exact settings that produced a result. These tasks are often supported by different libraries and interfaces. A circuit can therefore be technically executable while remaining difficult to inspect, reproduce, or teach.

Classical simulation is an important part of quantum-software development: it enables algorithm prototyping, testing, and analysis before or alongside access to quantum processors. However, state-vector simulation stores an amplitude for every computational basis state, giving memory proportional to 2^n for n qubits; a dense density matrix scales as 4^n. These costs limit simulation on ordinary machines and make early resource estimates useful, not optional [1], [2]. Specialized toolkits such as ProjectQ, QuEST, and Qulacs focus on flexible compilation, high performance, or large-scale simulation [3]–[5]. Visual simulators and integrated educational environments also exist, including Psitrum [8]. QScope is not intended to replace these systems or compete with their high-performance backends.

This paper describes QScope as an integrated local workspace for the cycle **build → plan → run → inspect → revise**. The application pairs a Python/NumPy simulation engine with a React/TypeScript interface and a local FastAPI service. It supports circuit construction and import, ideal and noisy simulation, intermediate-state tracing, analysis, optimization, batch experiments, benchmark measurement, run history, and portable project files. The central engineering goal is to make execution assumptions visible throughout the workflow.

The paper makes four contributions:

1. It documents a single-circuit engine with state-vector, density-matrix, and Monte Carlo trajectory representations and explicit labels distinguishing simulation modes.
2. It presents a preflight execution planner and a memory-bounded concurrent scheduler for independent batch jobs, including stable result ordering and actionable refusal when a job exceeds its budget.
3. It describes an integrated inspection and provenance workflow connecting circuit edits to traces, analysis, optimization verification, and saved run settings.
4. It reports functional verification and a reproducible, small-scale local benchmark, with limitations stated alongside the measurements.

QScope’s intended contribution is software integration and transparency. The simulator does not turn a classical laptop into quantum hardware, and none of the results reported here constitute a quantum-advantage claim.

## II. BACKGROUND AND RELATED WORK

### A. Classical simulation representations

For a pure n-qubit state, a state-vector representation stores 2^n complex amplitudes. With complex double-precision values, the raw state array requires approximately 16·2^n bytes, before temporary arrays and application overhead. A dense density matrix stores 4^n complex values and is consequently practical for substantially fewer qubits. State vectors are appropriate for ideal unitary evolution and sampled pure-state trajectories; density matrices represent mixed states and can model supported noise channels directly. These are different computational representations, not interchangeable labels for the same calculation [1], [2], [4].

### B. Quantum software platforms

ProjectQ combines a Python-embedded quantum language, a compiler framework, simulator, and hardware backends [3]. QuEST is designed for high-performance simulation across multicore, GPU, and distributed environments, including state-vector and density-matrix calculations [4]. Qulacs emphasizes fast, flexible simulation and provides numerical performance techniques [5]. These systems establish a mature ecosystem of programmable quantum software; QScope does not claim that the underlying simulation algorithms are novel or faster.

Graphical and learning-oriented systems are also prior art. Psitrum provides a local simulator with circuit visualization, noise options, and intermediate-state inspection [8]. OpenQASM is a portable textual representation for quantum circuits, with later versions extending its control-flow and implementation-level expressiveness [6], [7]. Circuit debugging and testing have received dedicated research attention, for example in Cirquo’s process framework [10].

QScope’s differentiating design choice is to make **resource planning, execution provenance, tracing, verified optimization, and memory-bounded batch behavior** part of one local workflow. This is a system-level distinction, not a claim that each feature is unique in isolation. Unlike high-performance simulator projects, QScope prioritizes a coherent inspectable workflow over distributed, GPU, or hardware-provider execution. Unlike a circuit-only visualizer, it also includes experiment, benchmark, and result-history services.

**TABLE I. QUALITATIVE POSITIONING AGAINST SELECTED SOFTWARE PAPERS**

| System | Emphasis reported in cited work | QScope positioning |
|:--|:--|:--|
| ProjectQ [3] | Programmable framework, compiler, simulator, and extensible backends | QScope centers on a local GUI workflow and execution provenance rather than compiler extensibility |
| QuEST [4] | High-performance state-vector and density-matrix simulation with multicore, GPU, and distributed execution | QScope does not target GPU/HPC scale; it emphasizes memory preflight and budgeted independent batches |
| Qulacs [5] | Fast, flexible research simulator with performance techniques | QScope makes no speed claim; its focus is connecting runs to visual inspection and history |
| Psitrum [8] | Local simulator with GUI, circuit visualization, noise, and intermediate-state tracing | QScope is a close integrated-workspace precedent; the distinction emphasized here is resource planning, batch policy, run provenance, and verified optimization together |
| QScope | Local circuit workspace with three simulation representations, planning, traces, analysis, optimization, history, and batch experiments | The evaluated contribution is workflow integration and explicit execution boundaries, not a new simulator algorithm |

The comparison is qualitative and limited to each cited publication’s described emphasis. It is not a feature-complete audit of current software releases, and the table deliberately does not imply that competing tools lack capabilities not mentioned in their cited papers.

### C. QAOA as an example workload

QScope includes a parameterized QAOA Max-Cut circuit generator that constructs an initial superposition, cost rotations on graph edges, a transverse-field mixer, and terminal measurements [9]. The current implementation is an educational and experimental circuit template; it is not the constraint-preserving WSN cluster-head method described in the supplied sample document. That sample’s CP-QAOA algorithm and reported WSN measurements are not part of QScope and are not used as evidence in this paper.

## III. SYSTEM DESIGN

### A. Architecture

QScope is organized into four cooperating layers:

| Layer | Implementation | Responsibility |
|:--|:--|:--|
| Interface | React and TypeScript | Circuit editing, guided workflows, visualizations, settings, history, and reports |
| Local API | FastAPI and Pydantic | Input validation, circuit/document conversion, planning, simulation and experiment endpoints |
| Quantum engine | Python and NumPy | Circuit operations, state representations, measurement, noise, metrics, and tracing |
| Persistence | Local SQLite and files | Run history, versioned drafts, and generated/exported project artifacts |

The interface requests authoritative circuit documents and analysis results from the API rather than independently re-computing quantum metrics. The API is hosted locally; no cloud service or quantum-hardware provider is required for the core workflow. Optional model-based assistant behavior is not required for simulation and is not treated as a source of scientific measurements.

### B. Circuit representation and editing

A circuit document records the circuit name, qubit and classical-bit counts, ordered operations, metadata, a diagram, and a QASM representation. Operations include a name, targets, controls, parameters, and kind. The API validates imported or edited documents before returning a normalized circuit. The browser editor supports algorithm templates, gate construction, QASM import, wire selection, operation inspection and reordering, undo/redo, and saved drafts. Drafts are named and versioned in SQLite; restoring an earlier revision creates a new current revision instead of erasing the intervening history. Project bundles serialize a circuit and an allow-listed set of settings to a portable JSON file.

### C. Execution modes and provenance

The engine supports three principal representations:

* **State vector:** exact pure-state evolution for ideal circuits.
* **Density matrix:** exact evolution for supported mixed-state and noise calculations, subject to the high memory cost.
* **Trajectory:** stochastic sampling of noise branches over pure-state trajectories; finite-shot outcomes are approximate and carry statistical uncertainty.

Each execution result records its mode, backend, shot count, seed, noise description, timing, memory observations, and warnings. A simulated result is labeled as simulation; hardware estimates and hardware execution are not conflated with local numerical results. Noise is represented through configured channels, including supported Kraus-operator updates and readout effects. The implementation’s supported gates and channels are defined by the source code and API catalog, not by a claim of universal device-level fidelity.

### D. Preflight planning and memory-bounded parallelism

Before a run, QScope estimates representation-specific state and peak working memory. The planner compares the peak estimate with an explicit request budget, the `QSCOPE_MEMORY_MB` environment setting (with a legacy alias), or an available-memory-derived default. It selects state-vector simulation for ideal runs and, for noisy runs, chooses exact density-matrix evolution when the configured budget permits or trajectories otherwise. An explicit incompatible or over-budget request is refused with an explanation and a safe-qubit estimate.

Batch parallelism is **across independent circuits**, not a promise that individual gate operations execute concurrently. For each job the API supplies a planned peak-memory estimate. The scheduler forms ordered waves whose combined estimated peaks do not exceed the shared memory budget and whose size does not exceed the worker limit. Jobs in a multi-job wave run through a `ThreadPoolExecutor`; a single-job wave runs directly. Results are written back to their original input positions, preserving deterministic ordering. A job whose estimated peak alone exceeds the shared limit is allowed to reach the normal planner so that QScope can return its standard actionable refusal rather than silently dropping the job.

This policy trades unconstrained maximum concurrency for resource predictability. The memory limit is an estimate and cannot account perfectly for unrelated processes, allocator behavior, or all temporary allocations; it is therefore a guardrail, not a hard operating-system isolation boundary.

### E. Tracing, optimization, and experiment history

The trace service records the state and selected metrics after circuit operations, including amplitudes/probabilities and changes between steps where supported. Analysis endpoints expose circuit resources, state metrics, comparisons, and what-if results. The optimizer applies local rewrite rules and accounts for removed/added operations. For circuits within its configured proof size, it compares unitary action directly; for larger cases it uses randomized input-state checks and labels that evidence accordingly. Failed rewrites are reverted rather than silently committed. This distinction between proof-level and statistical verification is retained in the result.

Simulation runs may be stored with their inputs and settings for later inspection or reproduction. Reproduction means rerunning the recorded experiment with its stored seed and configuration; bit-for-bit repeatability is scoped to compatible engine and numerical-library behavior, not guaranteed across arbitrary software or hardware versions.

## IV. IMPLEMENTATION

The engine is implemented in Python with NumPy and uses a shared circuit model across execution, tracing, and optimization. FastAPI endpoints expose circuit validation/document conversion, planning, single and batch simulation, trace generation, analysis, optimization, experiment execution, reports, and history. Pydantic models validate request structure. The frontend is a TypeScript React single-page application with a local API client. The codebase’s declared minimum Python version is 3.11; the evaluation below used Python 3.12.14 and NumPy 2.3.5.

Circuit depth is computed from operation dependencies and disjoint-wire layers; it is not an observed hardware runtime. Similarly, the planner’s peak-memory number is a model estimate, while reported runtime and state-array memory are measurements from the local process. QScope marks measured values, estimated values, and explanatory notes separately.

The latest workspace also includes onboarding for a first Bell-pair experiment, draft versioning, project JSON import/export, selectable target wires, operation drag-reordering, and editor undo/redo. These interface functions reduce repeated manual setup but do not change the mathematical simulation model.

## V. EVALUATION METHODOLOGY

### A. Functional verification

The complete repository test suite was executed with pytest and reached completion with exit status 0. Tests cover gate and circuit behavior, QASM round-tripping, reproducibility from seeds, ideal and noisy simulation, planning and over-budget refusal, batch wave scheduling, trace outputs, optimization verification, API behavior, draft versioning, and project-bundle validation. In particular, scheduler tests check both (i) a batch whose combined estimated peaks fit in one concurrent wave and (ii) a tighter budget that forces sequential waves. These tests verify scheduling and result ordering; they do not measure a wall-clock speedup.

### B. Local scaling benchmark

The repository benchmark harness was used to time six-layer generated circuits at 6, 8, 10, 12, and 14 qubits. The generator applies seeded single-qubit rotations and a nearest-neighbor CNOT pattern, followed by measurement. Each run used 512 shots and a fixed execution seed. For each size, the harness performed one warm-up, then five timed repetitions with garbage collection disabled during the timed intervals. The table reports median wall-clock runtime and the max-minus-min spread across those five trials. It also reports the state-array memory returned by the engine. No extrapolated measurements are reported.

The test environment was Windows 11, Python 3.12.14, NumPy 2.3.5, and a processor reported by the runtime as Intel64 Family 6 Model 186, with 16 logical processors. The exact retail CPU model was unavailable from the sandbox. No GPU was used. These measurements are specific to this environment and this generated circuit family.

## VI. RESULTS

### A. Functional results

The test suite completed successfully. The batch scheduler’s tests confirmed that two independent jobs are placed in one wave when their estimated peaks fit the supplied shared budget, and in separate waves when only one job fits at a time. Results remain in source order. The simulation tests also verify that a seeded Bell-state run returns only correlated outcomes, that noisy simulation is labeled separately from ideal simulation, and that an over-budget circuit receives an explicit refusal. These are software correctness checks within the tested inputs; they are not formal verification of the entire application or of every possible circuit.

### B. Runtime and state-array memory

**TABLE II. LOCAL STATE-VECTOR SCALING MEASUREMENTS**

| Qubits | Gates | Depth | Median time (ms) | Trial spread (ms) | State array (MB) |
|---:|---:|---:|---:|---:|---:|
| 6 | 87 | 19 | 6.69 | 3.23 | 0.001024 |
| 8 | 117 | 19 | 16.04 | 4.02 | 0.004096 |
| 10 | 147 | 19 | 16.51 | 2.52 | 0.016384 |
| 12 | 177 | 19 | 57.64 | 4.22 | 0.065536 |
| 14 | 207 | 19 | 229.93 | 17.93 | 0.262144 |

Across the tested points, the median increased from 6.69 ms at 6 qubits to 229.93 ms at 14 qubits, approximately 34.4 times. The state-vector array increased by 256 times over the same eight-qubit increment, consistent with the 2^n representation size. A log-linear fit to these five runtimes yields an empirical multiplier of approximately 1.52 per additional qubit (R² ≈ 0.92). Because the circuit family and size range are small, the fit is descriptive only; it should not be extrapolated as a universal runtime law. The non-monotonic change between 8 and 10 qubits and the measured spreads demonstrate that short local timings contain system noise and overhead.

The benchmark supports two bounded conclusions: (1) the harness can produce repeatable, structured measurements with a documented procedure, and (2) classical state storage grows rapidly with qubit count even for small illustrative circuits. It does **not** establish a general speedup, performance superiority over Qiskit, QuEST, Qulacs, or another simulator, a laptop-wide qubit limit, or quantum advantage.

## VII. DISCUSSION

The principal result is an integrated software workflow whose stages share a circuit model and execution record. A user can edit a circuit, inspect a resource plan, execute it, trace intermediate states, and return to the settings associated with a stored result. This makes several common interpretation errors less likely: confusing simulated and hardware data, overlooking a noise model, treating a trajectory estimate as an exact density-matrix result, or interpreting circuit depth as wall-clock time.

The memory-aware batch scheduler addresses an operational issue distinct from quantum algorithm design. Launching all independent experiments simultaneously can multiply peak memory even when each job fits alone. QScope’s wave formation constrains concurrent estimated peaks and makes the selected schedule inspectable. The current evaluation establishes functional correctness of this policy but does not establish that threads improve throughput for all workloads. Python overhead, NumPy behavior, memory bandwidth, and circuit size can change whether concurrency helps; future evaluation should compare serial and concurrent throughput across controlled workload classes and machines.

The related systems show that accessible interfaces, noise simulation, and trace visualization are not new concepts [3]–[8]. QScope’s contribution should therefore be judged as the specific combination and behavior of its resource-planning, bounded batch execution, provenance, trace, and verification paths, as implemented and tested in this repository. A controlled usability study is needed before claiming that the interface is easier to learn or measurably improves task completion.

## VIII. LIMITATIONS AND FUTURE WORK

First, state-vector and dense density-matrix simulation remain exponentially costly in their applicable dimensions. A memory budget can prevent some avoidable failures, but it does not make large exact simulations practical. Second, the noisy trajectory backend is stochastic and has finite-shot error; exact and approximate outputs need to remain distinguished. Third, current performance evidence comes from a single Windows environment, one synthetic circuit family, and a small range of qubit counts. The run does not compare QScope against other simulators under matched versions, hardware, precision, thread settings, and noise semantics.

Fourth, scheduler tests establish wave formation, not actual speedup or robustness under external memory pressure. Fifth, optimizer equivalence guarantees are size-dependent: exact unitary comparisons are limited to small circuits, while larger-circuit checks are statistical and must be interpreted as such. Sixth, no formal human-subject usability study has been conducted, so accessibility and learning benefits are design goals rather than demonstrated outcomes. Finally, the project bundle and local persistence features have software tests, but broader compatibility and long-term schema migration require further validation.

Future work should add controlled cross-platform benchmarks; characterize scheduler throughput, peak resident memory, and fairness; broaden differential testing against independent simulator implementations; expand import/export conformance tests; publish versioned benchmark datasets; and conduct a preregistered usability study with novice and experienced participants. Optional hardware-provider integration should be clearly separated from the local simulation path and reported with device calibration and job provenance.

## IX. CONCLUSION

QScope is a local-first quantum-circuit simulation and research workspace that connects circuit construction, resource planning, execution, tracing, optimization, and experiment records. Its implementation supports ideal state-vector simulation, noisy density-matrix simulation, and sampled trajectories, with an explicit memory planner and a concurrent batch scheduler that respects estimated shared working-set limits. The complete software test suite passed, and a small five-trial benchmark measured the expected increase in state-vector memory and runtime across 6–14 qubits on one development machine. The evidence supports QScope as an inspectable, reproducible engineering tool; it does not support claims of hardware execution, broad performance superiority, improved learning outcomes, or quantum advantage. The most important next step is rigorous cross-platform and user-centered evaluation.

## ACKNOWLEDGMENT

The author should add any required project, institutional, or funding acknowledgments here. Do not include an organization or funding source unless it actually applies.

## REFERENCES

[1] M. A. Nielsen and I. L. Chuang, *Quantum Computation and Quantum Information*, 10th anniversary ed. Cambridge, U.K.: Cambridge University Press, 2010.

[2] J. Preskill, “Quantum computing in the NISQ era and beyond,” *Quantum*, vol. 2, p. 79, 2018, doi: 10.22331/q-2018-08-06-79.

[3] D. S. Steiger, T. Häner, and M. Troyer, “ProjectQ: An open source software framework for quantum computing,” *Quantum*, vol. 2, p. 49, 2018, doi: 10.22331/q-2018-01-31-49.

[4] T. Jones, A. Brown, I. Bush, and S. Benjamin, “QuEST and high performance simulation of quantum computers,” *Scientific Reports*, vol. 9, art. 10736, 2019, doi: 10.1038/s41598-019-47174-9.

[5] Y. Suzuki *et al*., “Qulacs: A fast and versatile quantum circuit simulator for research purpose,” *Quantum*, vol. 5, p. 559, 2021, doi: 10.22331/q-2021-10-06-559.

[6] A. W. Cross, L. S. Bishop, J. A. Smolin, and J. M. Gambetta, “Open quantum assembly language,” arXiv:1707.03429, 2017.

[7] A. W. Cross *et al*., “OpenQASM 3: A broader and deeper quantum assembly language,” *ACM Transactions on Quantum Computing*, vol. 3, no. 3, 2022, doi: 10.1145/3505636.

[8] M. Alghadeer *et al*., “Psitrum: An open source simulator for universal quantum computers,” *IET Quantum Communication*, vol. 5, no. 4, pp. 586–600, 2024, doi: 10.1049/qtc2.12101.

[9] E. Farhi, J. Goldstone, and S. Gutmann, “A quantum approximate optimization algorithm,” arXiv:1411.4028, 2014.

[10] S. A. Metwalli and R. Van Meter, “Testing and debugging quantum circuits,” arXiv:2311.18202, 2023.

## REPRODUCIBILITY NOTE

The local timing table was generated with QScope’s `benchmark_scaling` routine using `compute_circuit(n, depth=6)`, qubit counts (6, 8, 10, 12, 14), 512 shots, five measured trials, one warm-up per point, and the benchmark’s fixed seeds. The benchmark implementation is in `qscope/experiments/benchmark.py`. The full automated test suite was run from the repository root using pytest. For a publication or external selection submission, record the repository commit hash, operating-system build, exact CPU model, memory capacity, Python and NumPy versions, and test command at submission time; rerun the benchmark from that frozen revision.
