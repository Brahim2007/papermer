from experiments.modal_scope_v3_1_1 import CORPUS_SHA256, DOCUMENT_COUNT, GPU


def test_modal_scope_v3_1_1_is_hash_locked():
    assert GPU == "L4"
    assert DOCUMENT_COUNT == 52493
    assert CORPUS_SHA256 == (
        "2d80460bd329c2c5401478320f3dbd1e6d35806631ce4df1e5d96fa280af765f"
    )
