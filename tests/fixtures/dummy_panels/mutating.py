# Test-only panel plugin fixture (v1.9.0). Not shipped; registered by tests/fixtures/dummy_panels-0.0.0.dist-info.
# © 2026 ShadowStrike. MIT License.

from dummy_panels._base import PLUGIN_API, VERSION, describe_for, summary_rows

NAME = "dummy-mutating"


def describe():
    return describe_for(NAME)


def panel(session_export):
    rows = summary_rows(session_export)
    # Scribbles over its input: the host must have passed a copy.
    session_export["session"]["name"] = "overwritten"
    session_export["session"]["timer"].clear()
    for c in session_export["challenges"]:
        c["status"] = "unsolved"
        c["points"] = -1
        c.clear()
    session_export["challenges"].append({"injected": True})
    return {"title": "Dummy mutating", "rows": rows}
