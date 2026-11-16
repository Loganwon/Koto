from companion.agent_lab.execution_evidence import source_reads
from companion.agent_lab.review_scope import identity


def test_only_actual_version_bound_access_proves_source_read():
    ref = {
        "file_id": "policy.txt",
        "sha256": "h",
        "snapshot_version": "v1",
        "text": "abcd",
        "characters": 4,
        "observed_methods": ["read"],
        "observed_ranges": [{"start": 0, "end": 2}, {"start": 2, "end": 4}],
    }
    value = source_reads({"references": [ref]})
    assert value[0]["fully_observed_text"] is True and value[0]["text"] == "abcd"
    gap = source_reads(
        {"references": [{**ref, "observed_ranges": [{"start": 1, "end": 4}]}]}
    )
    assert gap[0]["fully_observed_text"] is False and "text" not in gap[0]
    assert (
        source_reads({"references": [{"file_id": "unread.txt", "sha256": "h"}]}) == []
    )
    assert value[0]["sha256"] == "h" and value[0]["snapshot_version"] == "v1"


def test_receipt_repetition_is_stable_but_new_access_invalidates_review():
    ref = {
        "file_id": "orders.csv",
        "sha256": "h",
        "text": "a,b",
        "characters": 3,
        "observed_methods": ["read"],
        "observed_ranges": [{"start": 0, "end": 3}],
    }
    one = source_reads({"references": [ref]})
    assert one == source_reads(
        {
            "references": [
                {
                    **ref,
                    "observed_methods": ["read", "search"],
                    "observed_ranges": ref["observed_ranges"] * 2,
                }
            ]
        }
    )
    base = {"file_name": "清单.xlsx", "execution_sources": []}
    assert identity(base) != identity({**base, "execution_sources": one})


def test_query_input_is_not_fabricated_full_text_access():
    value = source_reads(
        {
            "references": [
                {
                    "file_id": "big.csv",
                    "sha256": "h",
                    "binding": "structured_query",
                    "text": "preview",
                    "characters": 10000,
                    "truncated": True,
                }
            ]
        }
    )
    assert value[0]["structured_query_input"] is True
    assert not value[0]["fully_observed_text"] and "text" not in value[0]
