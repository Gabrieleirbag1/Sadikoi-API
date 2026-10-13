"""Every route of the API must have been exercised by the suite (runs last, needs the whole suite)."""
import pytest

from tests.conftest import HIT_ROUTES


def test_every_route_is_exercised(app, request):
    if request.config.args not in ([], ["tests"], ["tests/"]):
        pytest.skip("route coverage is only meaningful when the whole suite runs")
    declared = {
        (method, rule.rule)
        for rule in app.url_map.iter_rules()
        if rule.endpoint != "static"
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }
    missing = sorted(declared - HIT_ROUTES)
    assert not missing, f"routes never hit by any test: {missing}"
