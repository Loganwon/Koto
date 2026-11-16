"""Preservation checks use verified old draft bytes, not current source facts."""

import hashlib
from types import SimpleNamespace

from companion.agent_lab.editing_baseline import collect
from companion.workspace import LocalWorkspace


def setup(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    sources = tmp_path / "references"
    sources.mkdir()
    original = sources / "旧稿.txt"
    original.write_text("原稿金额100元。", encoding="utf8")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    workspace = LocalWorkspace()
    workspace.open(sources)
    events = []
    broker = SimpleNamespace(
        outputs=outputs,
        workspace=workspace,
        task="task",
        store=SimpleNamespace(events=lambda _: events, get=lambda _: {"user_requests": []}),
    )

    def receipt(action, name, copied_from):
        events.append(
            {
                "kind": "action_verified",
                "body": {
                    "result": {
                        "action": action,
                        "name": name,
                        "copied_from": copied_from,
                        "sha256": digest,
                    }
                },
            }
        )

    receipt("copy_reference", "副本.txt", "旧稿.txt")
    return broker, original, digest, receipt


def test_copy_then_rename_retains_original_draft_instead_of_new_content(tmp_path):
    broker, original, digest, receipt = setup(tmp_path)
    (broker.outputs / "副本.txt").write_bytes(original.read_bytes())
    receipt("copy_artifact", "二稿.txt", "副本.txt")
    receipt("rename_artifact", "终稿.txt", "二稿.txt")
    (broker.outputs / "终稿.txt").write_text(
        "修改后100元，新增200元。", encoding="utf8"
    )
    baseline = collect(broker, "终稿.txt")
    assert baseline["text"] == original.read_text(encoding="utf8")
    assert baseline["sha256"] == digest
    assert baseline["role"] == "editing_baseline_not_fact_source"


def test_changed_source_never_substitutes_for_copied_baseline(tmp_path):
    broker, original, _, _ = setup(tmp_path)
    original.write_text("新来源有200元。", encoding="utf8")
    baseline = collect(broker, "副本.txt")
    assert baseline["unavailable"] and "text" not in baseline


def test_missing_reference_can_use_verified_archive_but_not_corrupt_archive(tmp_path):
    broker, original, digest, _ = setup(tmp_path)
    versions = broker.outputs.parent / "artifact_versions"
    versions.mkdir()
    archive = versions / (digest + ".txt")
    archive.write_bytes(original.read_bytes())
    original.unlink()
    assert collect(broker, "副本.txt")["text"] == "原稿金额100元。"
    archive.write_text("伪造的旧稿。", encoding="utf8")
    assert collect(broker, "副本.txt")["unavailable"]


def test_generated_output_without_copy_lineage_has_no_draft_baseline(tmp_path):
    broker, _, _, _ = setup(tmp_path)
    assert collect(broker, "新生成.txt") is None


def test_copy_of_a_revised_artifact_uses_its_immediate_copy_version(tmp_path):
    broker, _, _, receipt = setup(tmp_path)
    revised = broker.outputs / "副本.txt"
    revised.write_text("修订稿已有200元。", encoding="utf8")
    digest = hashlib.sha256(revised.read_bytes()).hexdigest()
    receipt("copy_artifact", "二稿.txt", "副本.txt")
    broker.store.events(None)[-1]["body"]["result"]["sha256"] = digest
    receipt("rename_artifact", "终稿.txt", "二稿.txt")
    (broker.outputs / "终稿.txt").write_text("又修改为300元。", encoding="utf8")
    baseline = collect(broker, "终稿.txt")
    assert baseline["sha256"] == digest
    assert baseline["file_id"] == "副本.txt"
    assert baseline["text"] == "修订稿已有200元。"
