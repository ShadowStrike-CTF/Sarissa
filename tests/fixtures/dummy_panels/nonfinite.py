# Test-only panel plugin fixture (v1.9.0). Not shipped; registered by tests/fixtures/dummy_panels-0.0.0.dist-info.
# © 2026 ShadowStrike. MIT License.

from dummy_panels._base import PLUGIN_API, VERSION, describe_for

NAME = "dummy-nonfinite"


def describe():
    return describe_for(NAME)


def panel(session_export):
    return {"title": "Dummy nonfinite", "rows": [{"label": "x", "value": float("nan")}]}
