from __future__ import annotations

from qscope.experiments.drafts import CircuitDraftStore


def test_draft_save_versions_favorite_and_restore(tmp_path) -> None:
    store = CircuitDraftStore(tmp_path / "qscope.sqlite3")
    first_document = {"name": "bell", "num_qubits": 2, "operations": []}
    second_document = {"name": "bell", "num_qubits": 2, "operations": [{"name": "H"}]}

    created = store.save(name="Bell study", document=first_document)
    updated = store.save(
        draft_id=created["draft_id"], name="Bell study", document=second_document, favorite=True
    )

    assert created["version"] == 1
    assert updated["version"] == 2
    assert updated["favorite"] is True
    assert store.get(created["draft_id"])["document"] == second_document
    assert [revision["version"] for revision in store.versions(created["draft_id"])] == [2, 1]

    restored = store.restore(created["draft_id"], 1)
    assert restored["version"] == 3
    assert restored["document"] == first_document
    assert store.get(created["draft_id"])["favorite"] is True


def test_draft_delete_cascades_to_revision_history(tmp_path) -> None:
    store = CircuitDraftStore(tmp_path / "qscope.sqlite3")
    draft = store.save(name="Temporary", document={"operations": []})

    assert store.delete(draft["draft_id"]) is True
    assert store.get(draft["draft_id"]) is None
    assert store.delete(draft["draft_id"]) is False
