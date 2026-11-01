# Test-only panel plugin fixture (v1.9.0). Not shipped; registered by tests/fixtures/dummy_panels-0.0.0.dist-info.
# © 2026 ShadowStrike. MIT License.

from dummy_panels._base import PLUGIN_API, VERSION, describe_for

NAME = "dummy-table"


def describe():
    return describe_for(NAME)


def panel(session_export):
    return {
        "title": "Dummy table",
        "columns": ["Name", "Points", "Ratio"],
        "table": [[c["name"], c["points"], 0.5] for c in session_export["challenges"]],
    }
