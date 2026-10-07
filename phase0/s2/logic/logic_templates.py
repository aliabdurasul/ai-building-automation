"""S2 equipment logic templates (CPython, deterministic, vendor-neutral, no LLM).

Equipment behaviour lives here, not in the generator or the CODESYS adapter. A canonical model selects a
template per equipment instance and binds the template's slots to its own PLC variables:

    "equipment": [{"id": "PUMP-01", "type": "PUMP",
                   "logic": {"template": "PUMP_BASIC_V1", "bind": {"StartCommand": "PUMP01_StartCommand", ...}}}]

Unbound slots default to the variable of the same name. Rules (code LOGIC_TEMPLATE):
  * the template exists and is made for the equipment type;
  * every slot is bound to a declared variable of the slot's PLC type;
  * a bound variable belongs to the same equipment instance (no instance drives another's variables);
  * no variable is bound by two template instances.
A template body is IEC 61131-3 ST text with {{slot}} / {{parameter}} / {{equipment}} placeholders; output
order = model equipment order. Optional template "parameters" are named non-negative integer constants
(e.g. timer presets in ms); a model may override them per instance with "params". Templates are bundled
(content + sha256) into each revision so reproduction never depends on files that may change later.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA = "ai_bms.logic_template.v1"
BUNDLE_SCHEMA = "ai_bms.logic_template_bundle.v1"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def err(message: str) -> dict:
    return {"code": "LOGIC_TEMPLATE", "message": message}


def uses_templates(canon: dict) -> bool:
    return any(isinstance(e.get("logic"), dict) for e in canon.get("equipment") or [])


def referenced(canon: dict) -> list[str]:
    return sorted({e["logic"]["template"] for e in canon.get("equipment") or []
                   if isinstance(e.get("logic"), dict) and isinstance(e["logic"].get("template"), str)})


def make_bundle(canon: dict, template_dir: Path = TEMPLATE_DIR) -> bytes | None:
    """Referenced templates (sorted) as canonical JSON bytes; None for models without templates."""
    if not uses_templates(canon):
        return None
    tpls = {}
    for tid in referenced(canon):
        p = Path(template_dir) / f"{tid}.json"
        if p.is_file():
            raw = p.read_bytes()
            tpls[tid] = {"sha256": hashlib.sha256(raw).hexdigest(), "template": json.loads(raw.decode("utf-8"))}
    return (json.dumps({"schema": BUNDLE_SCHEMA, "templates": tpls}, indent=2, sort_keys=True) + "\n").encode("utf-8")


def bindings(eq: dict, tpl: dict) -> dict:
    bind = eq["logic"].get("bind") or {}
    return {slot: bind.get(slot, slot) for slot in tpl["slots"]}


def parameters(eq: dict, tpl: dict) -> dict:
    over = eq["logic"].get("params") or {}
    return {p: over.get(p, v) for p, v in sorted((tpl.get("parameters") or {}).items())}


def check(canon: dict, bundle: dict) -> list[dict]:
    errors = []
    variables = canon.get("variables") or {}
    owner: dict[str, str] = {}
    for eq in canon.get("equipment") or []:
        logic = eq.get("logic")
        if logic is None or logic == "none":
            continue
        if not isinstance(logic, dict):
            errors.append(err(f"{eq.get('id')}: free-text logic is not allowed in a templated model; "
                              f"use {{\"template\": ..., \"bind\": {{...}}}} or omit 'logic'"))
            continue
        tid = logic.get("template")
        entry = bundle["templates"].get(tid) if isinstance(tid, str) else None
        if entry is None:
            errors.append(err(f"{eq.get('id')}: unknown logic template {tid!r}"))
            continue
        tpl = entry["template"]
        if tpl.get("schema") != SCHEMA:
            errors.append(err(f"{tid}: template schema must be {SCHEMA!r}"))
            continue
        if tpl["equipment_type"] != eq.get("type"):
            errors.append(err(f"{eq.get('id')}: template {tid} is for equipment type {tpl['equipment_type']}, "
                              f"equipment is {eq.get('type')!r}"))
        unknown = sorted(set(logic.get("bind") or {}) - set(tpl["slots"]))
        if unknown:
            errors.append(err(f"{eq.get('id')}: bind names unknown slots {unknown} of {tid}"))
        unknown = sorted(set(logic.get("params") or {}) - set(tpl.get("parameters") or {}))
        if unknown:
            errors.append(err(f"{eq.get('id')}: params names unknown parameters {unknown} of {tid}"))
        for p, v in parameters(eq, tpl).items():
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                errors.append(err(f"{eq.get('id')}: parameter {p} of {tid} must be a non-negative integer (got {v!r})"))
        for slot, var in bindings(eq, tpl).items():
            v = variables.get(var)
            if v is None:
                errors.append(err(f"{eq.get('id')}: slot {slot} of {tid} bound to undeclared variable {var!r}"))
                continue
            if v["type"] != tpl["slots"][slot]:
                errors.append(err(f"{eq.get('id')}: slot {slot} of {tid} needs {tpl['slots'][slot]}, "
                                  f"variable {var} is {v['type']}"))
            if v.get("equipment") != eq.get("id"):
                errors.append(err(f"{eq.get('id')}: slot {slot} bound to {var}, which belongs to equipment "
                                  f"{v.get('equipment')!r} (equipment isolation)"))
            if var in owner and owner[var] != eq.get("id"):
                errors.append(err(f"variable {var} is bound by the logic of both {owner[var]} and {eq.get('id')}"))
            owner.setdefault(var, eq.get("id"))
    return errors


def render(canon: dict, bundle: dict) -> list[str]:
    """ST logic lines for all templated equipment, in model equipment order."""
    lines: list[str] = []
    for eq in canon["equipment"]:
        if not isinstance(eq.get("logic"), dict):
            continue
        tpl = bundle["templates"][eq["logic"]["template"]]["template"]
        values = dict(bindings(eq, tpl), **{p: str(v) for p, v in parameters(eq, tpl).items()}, equipment=eq["id"])
        for line in tpl["body"]:
            lines.append(PLACEHOLDER.sub(lambda m: values[m.group(1)], line))
    return lines


def instances(canon: dict, bundle: dict) -> list[dict]:
    """Per templated equipment: template id, sha256, bindings and the template's behaviour test."""
    out = []
    for eq in canon.get("equipment") or []:
        if not isinstance(eq.get("logic"), dict):
            continue
        entry = bundle["templates"][eq["logic"]["template"]]
        tpl = entry["template"]
        inst = {"equipment": eq["id"], "type": eq.get("type"), "template": tpl["id"], "sha256": entry["sha256"],
                "bind": bindings(eq, tpl), "behavior_test": tpl.get("behavior_test")}
        if tpl.get("parameters"):
            inst["parameters"] = parameters(eq, tpl)
        out.append(inst)
    return out
