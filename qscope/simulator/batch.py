"""Memory-bounded concurrent execution for independent circuit batches."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from qscope.circuit import Circuit
from qscope.simulator.execution import RunOptions
from qscope.simulator.simulator import run_circuit


def run_batch_jobs(
    jobs: list[tuple[Circuit, RunOptions, int]], memory_limit_bytes: int, worker_limit: int
) -> tuple[list[Any], list[list[int]]]:
    """Run independent circuit jobs in stable-order, memory-bounded waves.

    Each job contains a circuit, its run options, and the planned peak bytes.
    The scheduler never combines jobs whose estimated peaks exceed the shared
    budget. A job larger than the budget still runs alone so the normal execution
    planner can return its actionable refusal instead of the scheduler hiding it.
    """
    worker_limit = max(1, min(len(jobs), worker_limit))
    waves: list[list[int]] = []
    wave: list[int] = []
    wave_bytes = 0
    for index, (_, _, peak_bytes) in enumerate(jobs):
        if wave and (len(wave) >= worker_limit or wave_bytes + peak_bytes > memory_limit_bytes):
            waves.append(wave)
            wave, wave_bytes = [], 0
        wave.append(index)
        wave_bytes += peak_bytes
    if wave:
        waves.append(wave)

    results: list[Any] = [None] * len(jobs)
    for indices in waves:
        if len(indices) == 1:
            index = indices[0]
            results[index] = run_circuit(jobs[index][0], jobs[index][1])
        else:
            with ThreadPoolExecutor(max_workers=len(indices), thread_name_prefix="qscope-batch") as pool:
                futures = {index: pool.submit(run_circuit, jobs[index][0], jobs[index][1]) for index in indices}
                for index in indices:
                    results[index] = futures[index].result()
    return results, waves
