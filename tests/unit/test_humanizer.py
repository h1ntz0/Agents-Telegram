"""Unit tests for the Humanizer engine."""

from src.infrastructure.security.humanizer import humanize_response


def test_humanizer_removes_robotic_intros():
    raw = "Certainly! Here is a breakdown of the database schema for you."
    cleaned = humanize_response(raw)
    assert not cleaned.lower().startswith("certainly")
    assert not cleaned.lower().startswith("here is a breakdown")


def test_humanizer_removes_unprompted_conclusion():
    raw = (
        "We configured the database connection pooling.\n\n"
        "### Conclusion\n"
        "In summary, this implementation provides high throughput and reliability."
    )
    cleaned = humanize_response(raw)
    assert "Conclusion" not in cleaned
    assert "We configured the database connection pooling." in cleaned


def test_humanizer_replaces_buzzwords():
    raw = "Let's delve into this code. It stands as a testament to the rich tapestry of modern software."
    cleaned = humanize_response(raw)
    assert "delve into" not in cleaned
    assert "stands as a testament" not in cleaned
    assert "rich tapestry" not in cleaned
