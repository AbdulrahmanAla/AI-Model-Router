from app.chat import parse_freeform


def test_parse_freeform_normalizes_implicit_multiplication() -> None:
    parsed = parse_freeform("What is the integral of 2x + cos(x)?")

    assert parsed is not None
    assert parsed["operation"] == "integral"
    assert parsed["expression"] == "2*x+cos(x)"


def test_parse_freeform_keeps_plain_conversation_as_prompt_boundary() -> None:
    assert parse_freeform("Hi, can you help me?") is None


def test_parse_freeform_accepts_equation_colon_phrasing() -> None:
    parsed = parse_freeform("Solve for x: x^2 - 4 = 0")

    assert parsed is not None
    assert parsed["operation"] == "equation"
    assert parsed["expression"] == "x^2-4=0"


def test_parse_freeform_accepts_polite_calculus_phrasing() -> None:
    cases = {
        "Can you differentiate x^2?": "derivative",
        "Please find the integral of x^2": "integral",
        "Find d/dx of x^2": "derivative",
        "What is the derivative of x^2 with respect to x?": "derivative",
        "Can you solve x^2 - 4 = 0?": "equation",
        "What are the roots of x^2 - 4 = 0?": "equation",
    }

    for message, operation in cases.items():
        parsed = parse_freeform(message)
        assert parsed is not None, message
        assert parsed["operation"] == operation
