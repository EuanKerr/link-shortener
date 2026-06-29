from app.shortcode import ALPHABET, generate


def test_default_length_is_five():
    assert len(generate()) == 5


def test_custom_length():
    assert len(generate(10)) == 10


def test_only_base62_characters():
    allowed = set(ALPHABET)
    for _ in range(200):
        assert set(generate()) <= allowed


def test_alphabet_is_base62():
    assert len(ALPHABET) == 62
