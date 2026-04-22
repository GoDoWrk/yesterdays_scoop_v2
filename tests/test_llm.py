from app.services.llm import _hash_embedding


def test_hash_embedding_is_deterministic():
    one = _hash_embedding("hello world")
    two = _hash_embedding("hello world")
    three = _hash_embedding("goodbye")

    assert len(one) == 64
    assert one == two
    assert one != three
