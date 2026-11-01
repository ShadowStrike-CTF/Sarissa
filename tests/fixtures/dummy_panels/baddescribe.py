# Test-only panel plugin fixture (v1.9.0). Not shipped; registered by tests/fixtures/dummy_panels-0.0.0.dist-info.
# © 2026 ShadowStrike. MIT License.

from dummy_panels._base import PLUGIN_API, VERSION, describe_for, summary_rows

NAME = "dummy-baddescribe"


def describe():
    return describe_for(NAME, slot="scorer")


def panel(session_export):
    return {"title": "Dummy baddescribe", "rows": summary_rows(session_export)}
