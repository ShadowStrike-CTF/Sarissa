# Test-only panel plugin fixture (v1.9.0). Shared helpers for the dummy plugins.
# © 2026 ShadowStrike. MIT License.

PLUGIN_API = "1.0"
VERSION = "0.0.0"


def describe_for(name, version=VERSION, api=PLUGIN_API, slot="panel"):
    return {"name": name, "version": version, "api": api, "slot": slot}


def summary_rows(export):
    return [
        {"label": "Challenges", "value": len(export["challenges"])},
        {"label": "Schema", "value": export["schema_version"]},
        {"label": "Session", "value": export["session"]["name"]},
        {"label": "Empty", "value": None},
    ]
