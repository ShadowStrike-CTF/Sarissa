# Sarissa — plugin panel slot (Megdan Plugin Interface Spec v0.1.1).
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

"""Discover, load and run panel plugins. Plugins return data only; Sarissa draws it.

Loading rules: LR-1 allowlist (checked before any plugin code is imported), LR-2 API major
match, LR-3 failure isolation (a broken plugin is logged and skipped, never fatal).
"""

from __future__ import annotations

import copy
import logging
import math
import tomllib
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from sarissa._vendor.megdan_schema.plugin import (
    ENTRY_POINT_GROUPS,
    PLUGIN_API,
    REQUIRED_PLUGIN_ATTRIBUTES,
    SLOT_CALLABLES,
    PanelData,
    PluginDescription,
    Slot,
    is_api_compatible,
)

log = logging.getLogger("sarissa.plugins")

CONFIG_PATH = Path.home() / ".sarissa" / "config.toml"
PANEL_GROUP = ENTRY_POINT_GROUPS[Slot.PANEL]
PANEL_CALLABLE = SLOT_CALLABLES[Slot.PANEL]


@dataclass(frozen=True)
class LoadedPanel:
    name: str
    version: str
    plugin: Any

    def info(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version, "slot": Slot.PANEL.value}


def read_allowlist(path: Path | None = None) -> list[str]:
    """`[plugins] allow = [...]` from the config file. Read-only. Any problem → warning, []."""
    path = CONFIG_PATH if path is None else path
    try:
        with open(path, "rb") as fh:
            config = tomllib.load(fh)
    except FileNotFoundError:
        return []
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("config %s unreadable (%s); no plugins allowlisted", path, exc)
        return []
    plugins = config.get("plugins", {})
    allow = plugins.get("allow", []) if isinstance(plugins, dict) else None
    if not isinstance(allow, list) or not all(isinstance(n, str) for n in allow):
        log.warning("config %s: plugins.allow must be a list of names; no plugins allowlisted", path)
        return []
    return allow


def _check(ep_name: str, plugin: Any) -> LoadedPanel:
    """Raise ValueError (with the reason) unless the loaded object is a usable panel plugin."""
    missing = [a for a in (*REQUIRED_PLUGIN_ATTRIBUTES, PANEL_CALLABLE) if not hasattr(plugin, a)]
    if missing:
        raise ValueError(f"missing attribute(s): {', '.join(missing)}")
    if plugin.NAME != ep_name:
        raise ValueError(f"NAME {plugin.NAME!r} does not match entry point {ep_name!r}")
    if not is_api_compatible(plugin.PLUGIN_API, PLUGIN_API):
        raise ValueError(f"PLUGIN_API {plugin.PLUGIN_API!r} incompatible with host {PLUGIN_API}")
    desc = PluginDescription.model_validate(plugin.describe())
    if (desc.name, desc.version, desc.slot) != (plugin.NAME, plugin.VERSION, Slot.PANEL):
        raise ValueError("describe() does not match NAME / VERSION / slot 'panel'")
    if not callable(getattr(plugin, PANEL_CALLABLE)):
        raise ValueError(f"{PANEL_CALLABLE} is not callable")
    return LoadedPanel(name=desc.name, version=desc.version, plugin=plugin)


def load_panels(allow: Iterable[str]) -> list[LoadedPanel]:
    """Load every allowlisted panel plugin that passes LR-1/2/3, in entry-point name order."""
    allowed = set(allow)
    if not allowed:
        return []
    loaded: list[LoadedPanel] = []
    seen: set[str] = set()
    for ep in sorted(entry_points(group=PANEL_GROUP), key=lambda e: e.name):
        if ep.name not in allowed or ep.name in seen:
            continue  # LR-1: never import code that is not allowlisted
        seen.add(ep.name)
        try:
            loaded.append(_check(ep.name, ep.load()))
        except Exception as exc:  # LR-3: any failure skips this plugin only
            log.warning("panel plugin %r skipped: %s", ep.name, exc)
    for name in sorted(allowed - seen):
        log.warning("allowlisted panel plugin %r not installed", name)
    return loaded


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    return True


def run_panels(export: dict[str, Any], panels: Iterable[LoadedPanel]) -> list[dict[str, Any]]:
    """`[{name, data}]` for each panel whose output is valid PanelData. Each gets its own deep copy."""
    out: list[dict[str, Any]] = []
    for p in panels:
        try:
            result = getattr(p.plugin, PANEL_CALLABLE)(copy.deepcopy(export))
            data = PanelData.model_validate(result).model_dump()
        except ValidationError as exc:
            log.warning("panel plugin %r returned invalid PanelData: %s", p.name, exc.errors()[:3])
            continue
        except Exception as exc:  # LR-3
            log.warning("panel plugin %r raised %s: %s", p.name, type(exc).__name__, exc)
            continue
        if not _finite(data):
            log.warning("panel plugin %r returned a non-finite number", p.name)
            continue
        out.append({"name": p.name, "data": data})
    return out
