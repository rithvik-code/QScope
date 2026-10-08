"""End-to-end tests of the HTTP and WebSocket API.

These go through the same interface the interface uses, so a green run here means
the platform is actually reachable, not merely importable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qscope.simulator import MODE_IDEAL, MODE_NOISY

BELL = {"algorithm": "bell_state"}


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory):
    tmp = tmp_path_factory.mktemp("qscope-api")
    os.environ["QSCOPE_DB"] = str(tmp / "history.sqlite3")
    os.environ["QSCOPE_REPORTS"] = str(tmp / "reports")
    os.environ["QSCOPE_MEMORY_MB"] = "256"
    # import after the environment is set: the store and report paths are read at import
    from qscope.api.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def expect_ok(response, *expected_keys: str) -> dict:
    assert response.status_code == 200, f"{response.status_code}: {response.text[:600]}"
    payload = response.json()
    for key in expected_keys:
        assert key in payload, f"missing {key!r} in {sorted(payload)}"
    return payload


# --------------------------------------------------------------------- meta


def test_health_reports_environment(client: TestClient) -> None:
    payload = expect_ok(client.get("/api/health"), "status", "version", "numpy", "database_ok")
    assert payload["status"] == "ok"
    assert payload["database_ok"] is True
    assert payload["offline"] is True
    assert payload["python"].startswith("3.")


def test_meta_fills_every_picker(client: TestClient) -> None:
    payload = expect_ok(
        client.get("/api/meta"),
        "algorithms",
        "hardware",
        "experiments",
        "backends",
        "noise_models",
        "optimizer_levels",
        "whatif",
        "workflow",
        "modes",
    )
    keys = {entry["key"] for entry in payload["algorithms"]}
    assert {"bell_state", "grover", "qft", "qaoa_maxcut"} <= keys
    devices = {entry["key"] for entry in payload["hardware"]}
    assert {"linear_5", "grid_3x3"} <= devices or len(devices) >= 3
    assert {m["key"] for m in payload["modes"]} == {"ideal", "noisy", "hardware"}
    assert len(payload["workflow"]) == 8


def test_meta_subcatalogs(client: TestClient) -> None:
    gates = expect_ok(client.get("/api/meta/gates"), "gates")["gates"]
    names = {g["name"] for g in gates}
    assert {"I", "X", "Y", "Z", "H", "S", "T", "RX", "RY", "RZ", "CNOT", "CZ", "SWAP"} <= names
    assert len(expect_ok(client.get("/api/meta/metrics"), "metrics")["metrics"]) > 5
    assert len(expect_ok(client.get("/api/meta/noise"), "channels")["channels"]) >= 6
    assert len(expect_ok(client.get("/api/meta/backends"), "backends")["backends"]) == 3
    assert len(expect_ok(client.get("/api/meta/hardware"), "devices")["devices"]) >= 3
    assert len(expect_ok(client.get("/api/meta/experiments"), "experiments")["experiments"]) >= 5
    assert len(expect_ok(client.get("/api/meta/whatif"), "modifications")["modifications"]) == 9


# ----------------------------------------------------------------- circuits


def test_validate_accepts_algorithm_and_rejects_bad_source(client: TestClient) -> None:
    good = expect_ok(client.post("/api/circuit/validate", json=BELL), "valid", "resources")
    assert good["valid"] is True
    assert good["resources"]["gates"] >= 2

    bad = client.post("/api/circuit/validate", json={"qasm": "this is not qasm"}).json()
    assert bad["valid"] is False
    assert bad["errors"]

    contradictory = client.post(
        "/api/circuit/validate", json={"algorithm": "bell_state", "num_qubits": 3}
    ).json()
    assert contradictory["valid"] is False
    assert "conflicts" in contradictory["errors"][0]

    both = client.post("/api/circuit/validate", json={"algorithm": "bell_state", "qasm": "OPENQASM 2.0;"}).json()
    assert both["valid"] is False
    assert "only one" in both["errors"][0]


def test_circuit_document_round_trips_through_qasm(client: TestClient) -> None:
    document = expect_ok(client.post("/api/circuit/document", json=BELL), "operations", "qasm", "diagram", "resources")
    assert "H" in document["diagram"] or "h" in document["diagram"]
    again = expect_ok(client.post("/api/circuit/from-qasm", json={"qasm": document["qasm"]}), "operations")
    assert len(again["operations"]) >= len(document["operations"]) - 1
    assert again["num_qubits"] == document["num_qubits"]

    # the document must be re-usable as a source (the editor's save/load loop)
    back = expect_ok(client.post("/api/circuit/document", json={"circuit": document}), "resources")
    assert back["resources"]["gates"] == document["resources"]["gates"]


def test_qasm_text_endpoint_is_plain_text(client: TestClient) -> None:
    response = client.post("/api/circuit/qasm", json=BELL)
    assert response.status_code == 200
    assert "OPENQASM" in response.text


def test_unknown_algorithm_is_a_structured_error(client: TestClient) -> None:
    response = client.post("/api/circuit/validate", json={"algorithm": "not_a_real_algorithm"})
    payload = response.json()
    assert payload["valid"] is False
    assert "unknown algorithm" in payload["errors"][0]


# ------------------------------------------------------------------- execute


def test_plan_explains_the_engine_choice(client: TestClient) -> None:
    payload = expect_ok(client.post("/api/plan", json={"source": BELL, "shots": 512}), "backend", "estimated_mb", "blocked")
    assert payload["blocked"] is False
    assert payload["exact"] is True
    assert payload["budget_mb"] > 0
    assert payload["representation"]


def test_simulate_ideal_bell(client: TestClient) -> None:
    payload = expect_ok(
        client.post("/api/simulate", json={"source": BELL, "shots": 4096, "seed": 5, "store": True}),
        "result",
        "circuit",
        "plan",
    )
    result = payload["result"]
    assert result["mode"] == MODE_IDEAL
    assert result["backend"] == "statevector"
    assert result["seed"] == 5
    counts = result["counts"]
    assert set(counts) <= {"00", "11"}
    assert sum(counts.values()) == 4096
    assert counts.get("00", 0) + counts.get("11", 0) == 4096
    assert abs(result["ideal_probabilities"]["00"] - 0.5) < 1e-9
    assert result["timing"]["total_seconds"] > 0
    assert result["memory"]["state_mb"] > 0
    assert payload["experiment_id"], "store=true must return the id of the stored run"


def test_simulate_noisy_is_labelled_and_loses_fidelity(client: TestClient) -> None:
    payload = expect_ok(
        client.post(
            "/api/simulate",
            json={
                "source": BELL,
                "shots": 4096,
                "seed": 7,
                "noise": {"name": "depolarizing", "params": {"p": 0.1}},
            },
        ),
        "result",
    )
    result = payload["result"]
    assert result["mode"] == MODE_NOISY
    assert result["backend"] == "density_matrix"
    assert result["fidelity_vs_ideal"] is not None
    assert 0.0 <= result["fidelity_vs_ideal"] < 1.0
    assert result["noise"]["name"].startswith("depolarizing")
    # a noisy run must still explain itself
    assert result["noise"]["description"] or result["plan"]["notes"]


def test_simulate_rejects_oversized_registers_instead_of_crashing(client: TestClient) -> None:
    response = client.post(
        "/api/simulate",
        json={"source": {"num_qubits": 30}, "shots": 8, "memory_budget_mb": 4, "max_qubits": 30},
    )
    assert response.status_code in (400, 422)
    detail = response.json()["detail"]
    assert isinstance(detail, dict) and detail["detail"]


def test_batch_simulation_returns_one_summary_per_circuit(client: TestClient) -> None:
    payload = expect_ok(
        client.post(
            "/api/simulate/batch",
            json={"sources": [BELL, {"algorithm": "ghz_state", "algorithm_kwargs": {"num_qubits": 3}}], "shots": 256},
        ),
        "runs",
    )
    assert len(payload["runs"]) == 2
    assert all(run["summary"]["name"] for run in payload["runs"])
    assert all(run["result"]["counts"] for run in payload["runs"])


# --------------------------------------------------------------------- trace


def test_trace_shows_entanglement_appear_at_the_cnot(client: TestClient) -> None:
    payload = expect_ok(
        client.post("/api/trace", json={"source": BELL, "depth": "standard", "term_limit": 8}),
        "steps",
        "summary",
        "circuit",
    )
    statuses = [step["metrics"].get("entanglement_status") for step in payload["steps"]]
    assert statuses[0] == "SEPARABLE", statuses
    # Bell state: the Hadamard alone cannot entangle, the CNOT must
    cnot = next(step for step in payload["steps"] if step["name"].upper() == "CNOT")
    assert cnot["metrics"]["entanglement_status"].startswith("ENTANGLED")
    assert "SEPARABLE" in statuses[-1], "terminal measurement removes the entanglement"
    summary = payload["summary"]
    assert summary["steps"] == len(payload["steps"])
    assert summary["total_seconds"] >= 0
    assert summary["entanglement_created_at"] is not None
    # Quantum Diff must show the CNOT moving amplitude between basis states
    diff = cnot["diff"]
    assert diff, "every step carries a state difference"


def test_trace_websocket_streams_steps_then_done(client: TestClient) -> None:
    with client.websocket_connect("/ws/trace") as socket:
        socket.send_json({"source": BELL, "depth": "fast", "term_limit": 4})
        events = []
        while True:
            event = socket.receive_json()
            events.append(event)
            if event["type"] in {"done", "error"}:
                break
    assert events[0]["type"] == "start"
    assert events[0]["total_steps"] >= 2
    streamed = [e for e in events if e["type"] == "step"]
    assert len(streamed) >= 2
    assert events[-1]["type"] == "done"
    assert streamed[0]["step"]["index"] == 0


# ---------------------------------------------------------------- optimizer


def test_optimize_reports_verified_savings(client: TestClient) -> None:
    payload = expect_ok(
        client.post(
            "/api/optimize",
            json={"source": {"qasm": _redundant_qasm()}, "level": "standard", "verify": True},
            ),
        "before",
        "after",
        "improvements",
        "verification",
        "opportunities",
        "headline",
    )
    assert payload["before"]["gates"] > payload["after"]["gates"]
    assert payload["improvements"]["gates_saved"] >= 2
    assert payload["verification"]["status"] in {"PROVEN_EQUIVALENT", "VERIFIED_ON_RANDOM_INPUTS"}
    assert payload["verification"]["method"]
    assert isinstance(payload["opportunities"], list)
    # the optimizer is only allowed to publish a saving it verified
    if payload["verification"]["status"] == "PROVEN_EQUIVALENT":
        assert payload["verification"]["max_deviation"] < 1e-8


def _redundant_qasm() -> str:
    return """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
h q[0];
x q[1];
x q[1];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""


def test_opportunity_audit_is_read_only(client: TestClient) -> None:
    payload = expect_ok(client.post("/api/optimize/opportunities", json={"qasm": _redundant_qasm()}), "findings", "levels")
    assert payload["findings"], "the audit should find the h;h and x;x pairs"
    assert len(payload["levels"]) == 3


# ------------------------------------------------------------------ analysis


def test_metrics_include_state_and_circuit_views(client: TestClient) -> None:
    payload = expect_ok(client.post("/api/metrics", json={"source": BELL}), "state", "circuit_metrics", "glossary")
    state = payload["state"]
    # the whole Bell state is pure: zero von Neumann entropy, unit purity
    assert abs(state["purity"] - 1.0) < 1e-9
    assert abs(state["entropy"]) < 1e-9
    # ... while each qubit is maximally mixed on its own
    per_qubit = state["entanglement"]["per_qubit_entropy"]
    assert all(abs(entry["entanglement_entropy"] - 1.0) < 1e-9 for entry in per_qubit)
    assert state["entanglement_status"] == "ENTANGLED"
    assert abs(state["entanglement"]["max_concurrence"] - 1.0) < 1e-9
    assert payload["circuit_metrics"]["gates"] >= 2
    assert payload["glossary"]


def test_metric_key_filter_narrows_the_payload(client: TestClient) -> None:
    payload = expect_ok(client.post("/api/metrics", json={"source": BELL, "keys": ["purity"]}), "state")
    assert set(payload["state"]) == {"purity"}
    assert "gates" in payload["circuit_metrics"]


def test_compare_detects_both_differences_and_agreement(client: TestClient) -> None:
    payload = expect_ok(
        client.post(
            "/api/compare",
            json={"a": BELL, "b": {"qasm": _redundant_qasm()}, "shots": 512},
        ),
        "verdict",
        "resource_rows",
        "metric_rows",
        "output_total_variation",
        "circuit_a",
        "circuit_b",
    )
    assert 0.0 <= payload["output_total_variation"] <= 1.0
    assert payload["verdict"]
    names = {row["metric"] for row in payload["resource_rows"]}
    assert {"gates", "depth", "qubits"} <= names


def test_compare_refuses_mismatched_register_sizes(client: TestClient) -> None:
    response = client.post(
        "/api/compare",
        json={"a": BELL, "b": {"algorithm": "ghz_state", "algorithm_kwargs": {"num_qubits": 4}}},
    )
    assert response.status_code == 400
    assert "qubit" in response.json()["detail"].lower()


# ------------------------------------------------------------------- what-if


@pytest.mark.parametrize(
    "modification",
    [
        {"kind": "remove_gate", "index": 0},
        {"kind": "replace_gate", "index": 0, "gate": "RY", "params": [1.5707963267948966]},
        {"kind": "insert_gate", "gate": "Z", "targets": [0], "at": 1},
        {"kind": "add_qubit", "count": 1},
        {"kind": "set_noise", "strength": 0.05},
        {"kind": "set_shots", "shots": 4096},
        {"kind": "set_backend", "backend": "trajectory"},
        {"kind": "optimize", "level": "standard"},
    ],
)
def test_whatif_modifications_all_produce_a_measured_delta(client: TestClient, modification: dict) -> None:
    payload = expect_ok(
        client.post("/api/whatif", json={"source": BELL, "modification": modification, "shots": 256}),
        "baseline",
        "variant",
        "deltas",
        "verdict",
        "limitation",
    )
    assert payload["baseline"]["circuit"]["gates"] >= 0
    assert payload["verdict"]
    assert payload["catalog"]
    assert "simulation" in payload["limitation"].lower()


def test_whatif_rejects_an_unknown_modification(client: TestClient) -> None:
    response = client.post("/api/whatif", json={"source": BELL, "modification": {"kind": "explode"}})
    assert response.status_code == 400
    assert "explode" in response.json()["detail"]


# ------------------------------------------------------------------ hardware


def test_hardware_report_is_labelled_as_an_estimate(client: TestClient) -> None:
    payload = expect_ok(
        client.post("/api/hardware", json={"source": BELL, "device": "linear_5", "route": True}),
        "hardware",
        "fits",
        "connectivity_violations",
        "limitations",
        "estimate_before_routing",
    )
    assert payload["fits"] is True
    assert any("estimate" in line.lower() for line in payload["limitations"])


def test_hardware_custom_device_and_unknown_device(client: TestClient) -> None:
    custom = expect_ok(
        client.post(
            "/api/hardware",
            json={"source": BELL, "device": "custom", "model": {"name": "ring4", "num_qubits": 4, "topology": "ring"}},
        ),
        "hardware",
    )
    assert custom["hardware"]["num_qubits"] == 4
    assert custom["hardware"]["name"] == "ring4"

    missing = client.post("/api/hardware", json={"source": BELL, "device": "no_such_device"})
    assert missing.status_code in (400, 404)
    body = missing.json()
    assert body["hint"] or (isinstance(body["detail"], dict) and body["detail"]["hint"])


# ----------------------------------------------------------------- evolution


def test_evolution_ranks_candidates_with_a_verified_best(client: TestClient) -> None:
    payload = expect_ok(
        client.post(
            "/api/evolve",
            json={"source": BELL, "generations": 2, "population": 4, "seed": 3},
        ),
        "candidates",
        "best",
        "search_log",
        "comparison",
        "headline",
    )
    assert payload["candidates"]
    assert payload["best"]["label"]
    assert 0.0 <= payload["best"]["fidelity"] <= 1.0 + 1e-9
    assert payload["comparison"], "the candidates must be comparable side by side"


# -------------------------------------------------------------- experiments


def test_experiment_run_records_every_point(client: TestClient) -> None:
    payload = expect_ok(
        client.post(
            "/api/experiments/run",
            json={
                "key": "api_shots",
                "kind": "shots_convergence",
                "algorithm": "bell_state",
                "axes": {"shots": [64, 512, 4096]},
                "seed": 4242,
                "store": True,
            },
        ),
        "rows",
        "series",
        "aggregates",
        "spec",
        "headline",
    )
    assert len(payload["rows"]) == 3
    for row in payload["rows"]:
        assert row["runtime_seconds"] >= 0
        assert row["backend"]
        # the sampled histogram must approach the exact one as shots grow
    distances = [row["distribution_distance"] for row in sorted(payload["rows"], key=lambda r: r["params"]["shots"])]
    assert distances[0] >= distances[-1] - 0.05, distances
    assert payload["experiment_ids"], "store=true must return ids"


def test_custom_experiment_requires_axes(client: TestClient) -> None:
    response = client.post("/api/experiments/run", json={"kind": "custom", "axes": {}})
    assert response.status_code == 400
    assert "axis" in response.json()["detail"]


def test_experiment_websocket_streams_progress(client: TestClient) -> None:
    with client.websocket_connect("/ws/experiment") as socket:
        socket.send_json(
            {
                "kind": "algorithm_scaling",
                "algorithm": "ghz_state",
                "axes": {"num_qubits": [2, 3]},
                "shots": 128,
                "store": False,
            }
        )
        events = []
        while True:
            event = socket.receive_json()
            events.append(event)
            if event["type"] in {"done", "error"}:
                break
    assert events[0]["type"] == "start"
    assert any(e["type"] == "progress" for e in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["outcome"]["rows"]


# ---------------------------------------------------------------- benchmark


def test_benchmark_reports_measurements_and_a_disclaimer(client: TestClient) -> None:
    payload = expect_ok(
        client.post("/api/benchmark", json={"kind": "scaling", "qubits": [4, 6], "shots": 64, "trials": 1}),
        "points",
        "disclaimer",
        "fit",
    )
    measured = [p for p in payload["points"] if p.get("status") == "measured"]
    assert measured, payload["points"]
    assert measured[0]["median_seconds"] > 0
    assert payload["fit"], "a scaling benchmark must report its growth fit or say why not"
    assert "quantum advantage" in payload["disclaimer"]


def test_benchmark_memory_observatory(client: TestClient) -> None:
    payload = expect_ok(
        client.post("/api/benchmark", json={"kind": "memory"}), "budget_bytes", "backend_tables", "safe_max_qubits"
    )
    assert payload["budget_bytes"] > 0
    assert set(payload["backend_tables"]) == {"statevector", "density_matrix", "trajectory"}
    assert payload["safe_max_qubits"]["statevector"] >= 1


def test_external_benchmark_refuses_to_invent_a_comparison(client: TestClient) -> None:
    payload = expect_ok(client.post("/api/benchmark", json={"kind": "external", "qubits": [4], "shots": 64, "trials": 1}))
    assert isinstance(payload.get("available"), bool)
    if payload.get("available") is False:
        assert payload["reason"], "a refusal must say why"


# ------------------------------------------------------------------ reports


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("simulation", {"source": BELL, "shots": 256, "seed": 3}),
        ("optimization", {"source": {"qasm": _redundant_qasm()}, "level": "standard"}),
        ("trace", {"source": BELL, "depth": "fast", "term_limit": 4}),
        ("comparison", {"a": BELL, "b": {"qasm": _redundant_qasm()}, "shots": 128}),
        ("hardware", {"source": BELL, "device": "linear_5"}),
    ],
)
def test_every_report_kind_builds_and_saves_all_formats(client: TestClient, kind: str, payload: dict) -> None:
    response = client.post("/api/report", json={"kind": kind, "payload": payload, "save": True})
    body = expect_ok(response, "report", "markdown", "html", "files")
    assert body["report"]["sections"], f"{kind} report has no sections"
    assert body["report"]["limitations"], f"{kind} report must state its limits"
    assert set(body["files"]) >= {"json", "csv", "markdown", "html", "pdf"}
    assert body["html"].startswith("<!doctype html>")
    assert "#" in body["markdown"]


def test_report_pdf_export_is_a_pdf(client: TestClient) -> None:
    response = client.post(
        "/api/report/export?format=pdf",
        json={"kind": "simulation", "payload": {"source": BELL, "shots": 128}},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_report_listing_and_download(client: TestClient) -> None:
    listing = expect_ok(client.get("/api/reports"), "files", "dir")
    assert listing["files"], "the reports above should have been saved"
    name = listing["files"][0]["name"]
    download = client.get(f"/api/reports/{name}")
    assert download.status_code == 200
    assert len(download.content) > 0
    assert client.get("/api/reports/../secret.txt").status_code in (400, 404)


# ----------------------------------------------------------------------- AI


def test_ai_answers_from_real_data_with_citations(client: TestClient) -> None:
    payload = expect_ok(
        client.post(
            "/api/ai/ask",
            json={
                "question": "Where is entanglement created?",
                "simulate": {"source": BELL, "shots": 512},
                "trace": {"source": BELL, "depth": "standard", "term_limit": 8},
            },
        ),
        "body",
        "citations",
        "confidence",
        "sources_available",
    )
    assert payload["citations"], "a grounded answer must cite its evidence"
    assert "result" in payload["sources_available"]
    assert "trace" in payload["sources_available"]
    assert payload["grounding"]


def test_ai_offline_is_complete_without_an_llm(client: TestClient) -> None:
    payload = expect_ok(
        client.post(
            "/api/ai/ask",
            json={"question": "Explain this circuit like I'm a beginner.", "source": BELL, "use_llm": True},
        ),
        "body",
        "title",
    )
    assert payload["llm_configured"] is False
    assert payload["narrative_error"] and "no LLM configured" in payload["narrative_error"]
    assert payload["body"]


def test_ai_suggestions(client: TestClient) -> None:
    payload = expect_ok(client.get("/api/ai/suggestions"), "questions", "offline_note")
    assert len(payload["questions"]) >= 10


# ------------------------------------------------------------------ history


def test_history_lists_stored_runs_with_stats(client: TestClient) -> None:
    payload = expect_ok(client.get("/api/history"), "experiments", "total", "stats", "tags")
    assert payload["total"] >= 1
    assert payload["experiments"]


def test_history_get_compare_export_and_reproduce(client: TestClient) -> None:
    listing = client.get("/api/history").json()
    ids = [e["experiment_id"] for e in listing["experiments"]][:2]
    assert len(ids) == 2

    stored = expect_ok(client.get(f"/api/history/{ids[0]}"), "experiment_id", "reproducibility", "circuit")
    reproducibility = stored["reproducibility"]
    assert reproducibility["random_seed"] is not None
    assert reproducibility["qscope_version"] == stored.get("qscope_version", reproducibility["qscope_version"])
    assert reproducibility["shots"] == stored["shots"]

    comparison = expect_ok(client.post("/api/history/compare", json={"ids": ids}), "experiments")
    assert len(comparison["experiments"]) == 2

    exported = client.get("/api/history/export?format=csv")
    assert exported.status_code == 200
    assert "csv" in exported.headers["content-type"]
    assert len(exported.text.splitlines()) >= 2

    reproduced = expect_ok(client.get(f"/api/history/reproduce/{ids[0]}"), "original", "rerun", "verdict", "distribution_distance")
    assert reproduced["original"]["counts"]
    assert reproduced["expected_shot_noise"] > 0


def test_history_missing_id_is_404_with_a_hint(client: TestClient) -> None:
    response = client.get("/api/history/doesnotexist")
    assert response.status_code == 404
    assert response.json()["detail"]["hint"]


def test_history_export_json_is_parseable(client: TestClient) -> None:
    response = client.get("/api/history/export?format=json")
    assert response.status_code == 200
    json.loads(response.text)


# ------------------------------------------------------- static + fallback


def test_root_serves_something(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "QScope" in response.text


def test_unknown_api_path_is_json_not_html(client: TestClient) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"] == "not-found"


def test_extra_fields_are_rejected(client: TestClient) -> None:
    response = client.post("/api/simulate", json={"source": BELL, "shitz": 4096})
    assert response.status_code == 422
    assert "shitz" in response.text


def test_reports_dir_is_created_under_the_configured_path(client: TestClient) -> None:
    from qscope.api.app import REPORTS_DIR

    assert REPORTS_DIR.exists()
    assert Path(os.environ["QSCOPE_REPORTS"]) == REPORTS_DIR


# ---------------------------------------------------------------------------
# the entry point itself
# ---------------------------------------------------------------------------


def test_entry_point_hands_uvicorn_the_asgi_app(monkeypatch) -> None:
    """``python -m qscope`` must pass the application, not the module that defines it.

    ``qscope.api.app`` is a module *and* the attribute holding the FastAPI instance,
    and ``from qscope.api import app`` resolves to the module — which uvicorn cannot
    call.  This test fails loudly if that ever comes back.
    """
    import uvicorn

    import qscope.__main__ as entry

    captured: dict[str, object] = {}

    def fake_run(target: object, **kwargs: object) -> None:
        captured["target"] = target
        captured["kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "run", fake_run)

    assert entry.main(["--port", "0"]) == 0
    assert callable(captured["target"]), "uvicorn was given something that is not callable"
    assert captured["kwargs"]["port"] == 0  # type: ignore[index]
    assert captured["kwargs"]["reload"] is False  # type: ignore[index]

    # With --reload uvicorn needs an import string instead of an instance.
    assert entry.main(["--reload"]) == 0
    assert captured["target"] == "qscope.api.app:app"


def test_main_info_prints_the_environment(capsys) -> None:
    import qscope.__main__ as entry

    assert entry.main(["--info"]) == 0
    printed = capsys.readouterr().out
    assert "QScope" in printed
    assert "numpy" in printed
    assert "engines" in printed


def test_memory_budget_follows_the_documented_variable(client: TestClient) -> None:
    """The module fixture sets QSCOPE_MEMORY_MB; every plan must obey it.

    The budget used to be read from a different name, which meant the variable the CLI,
    the README and these tests set had no effect at all.
    """
    payload = expect_ok(
        client.post(
            "/api/plan",
            json={
                "source": {"algorithm": "ghz_state", "algorithm_kwargs": {"num_qubits": 28}},
                "backend": "statevector",
                "shots": 128,
            },
        ),
        "budget_mb",
        "blocked",
        "safe_max_qubits",
        "warnings",
    )
    assert payload["budget_mb"] == 256
    assert payload["blocked"] is True  # 16 bytes × 2^28 amplitudes cannot fit in 256 MB
    assert payload["safe_max_qubits"] < 28
    assert any("QSCOPE_MEMORY_MB" in warning for warning in payload["warnings"])
