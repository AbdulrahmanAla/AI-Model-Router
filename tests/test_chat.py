from app.chat import parse_freeform


def test_parse_freeform_normalizes_implicit_multiplication() -> None:
    parsed = parse_freeform("What is the integral of 2x + cos(x)?")

    assert parsed is not None
    assert parsed["operation"] == "integral"
    assert parsed["expression"] == "2*x+cos(x)"


def test_parse_freeform_keeps_plain_conversation_as_prompt_boundary() -> None:
    assert parse_freeform("Hi, can you help me?") is None
