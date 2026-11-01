# Test-only panel plugin fixture (v1.9.0). Not shipped; registered by tests/fixtures/dummy_panels-0.0.0.dist-info.
# © 2026 ShadowStrike. MIT License.

from dummy_panels._base import VERSION, describe_for, summary_rows

PLUGIN_API = "2.0"
NAME = "dummy-wrong-api"


def describe():
    return describe_for(NAME, api=PLUGIN_API)


def panel(session_export):
    return {"title": "Dummy wrong api", "rows": summary_rows(session_export)}
