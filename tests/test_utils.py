"""utils.normalize_language: the app and Google send any locale, the API keeps a supported language."""
import pytest

from utils import normalize_language


@pytest.mark.parametrize("value, expected", [
    ("fr-FR", "fr"), ("FR", "fr"), ("en_US", "en"), ("en", "en"),
    ("de-DE", "en"), ("", "en"), (None, "en"), (42, "en"),
])
def test_normalize_language(value, expected):
    assert normalize_language(value) == expected


def test_custom_default():
    assert normalize_language("es", default="fr") == "fr"
