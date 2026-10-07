"""S2 offline architecture checks (CPython, measurement only; every check writes a result JSON).

  validation  --eng-root E --gen-root G --revision N          stored validation: every stage PASS incl. logic_template
  mapping     --eng-root E --gen-root G --revision N          allocator-chosen addresses (model carries none except
                                                              the pinned S1 words), every signal mapped once, inside
                                                              capacity, no overlaps, bound PLC image per channel
  isolation   --eng-root E --gen-root G --revision N --target T
                                                              identities/symbols/variables per equipment are disjoint;
                                                              mutations: same tag in two equipment ACCEPTED (distinct
                                                              identities), cross-equipment binding / duplicate symbol /
                                                              wrong template type / unknown template REJECTED
  template-equivalence --legacy-model M --legacy-target T --model M2 --target T2
                                                              AHU behaviour through template AHU_S1FIX_V1 == the S1/S3/S6
                                                              built-in AHU logic (same ST implementation)
  adapter-generic --adapter-dir D --models M... --control-file F
                                                              CODESYS adapter scripts contain no equipment type, id, tag
                                                              or PLC variable name of any model (F = a file known to
                                                              contain such names: proves the scanner detects them)
Exit: 0 PASS, 20 FAILED.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "s6" / "generator"))
import regenerate as rg  # noqa: E402

rv, cn = rg.rv, rg.cn


def jload(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def stored(a) -> dict:
    return rg.Store(a.eng_root, a.gen_root).read(a.revision)


def cmd_validation(a, res):
    f = stored(a)
    v = json.loads(f["engineering/validation.json"])
    c = res["checks"]
    c["status_accepted"] = v["status"] == "ACCEPTED"
    c["all_stages_pass"] = bool(v["stages"]) and all(s == "PASS" for s in v["stages"].values())
    c["logic_template_stage_ran"] = v["stages"].get("logic_template") == "PASS"
    c["templates_bundled"] = "engineering/logic_templates.json" in f and \
        v.get("logic_templates_sha256") == hashlib.sha256(f["engineering/logic_templates.json"]).hexdigest()
    c["no_errors"] = not v["errors"]
    res.update(stages=v["stages"], errors=v["errors"],
               templates={k: t["sha256"] for k, t in json.loads(f["engineering/logic_templates.json"])["templates"].items()}
               if "engineering/logic_templates.json" in f else None)


def cmd_mapping(a, res):
    f = stored(a)
    model = json.loads(f["engineering/model.json"])
    target = json.loads(f["engineering/target.json"])
    alloc = json.loads(f["engineering/allocation.json"])
    mapping = json.loads(f["engineering/modbus_mapping.json"])
    plan = json.loads(f["engineering/codesys_plan.json"])
    pid = model["project_id"]
    c = res["checks"]
    pinned = [rv.identity(pid, s) for s in model["signals"] if "address" in (s.get("modbus") or {})]
    c["only_s1_words_pinned_in_model"] = all(s.get("bits") for s in model["signals"] if "address" in (s.get("modbus") or {}))
    ids = [rv.identity(pid, s) for s in model["signals"]]
    act = {e["identity"]: e for e in alloc["active"]}
    c["every_signal_allocated_once"] = sorted(ids) == sorted(act) and len(alloc["active"]) == len(ids)
    c["every_signal_in_mapping"] = sorted(s["identity"] for s in mapping["signals"]) == sorted(ids)
    cap = target["platform"]["register_capacity"]
    cells, inside = {}, True
    for e in alloc["active"]:
        reg_area = cn.BIT_OVERLAY.get(e["area"], e["area"])
        limit = cap[reg_area] * (16 if e["area"] in cn.BIT_AREAS else 1)
        inside &= e["address"] + e["length"] <= limit
        for k in range(e["length"]):
            cells.setdefault((e["area"], e["address"] + k), []).append(e["identity"])
    c["inside_capacity"] = bool(inside)
    c["no_overlaps"] = all(len(v) == 1 for v in cells.values())
    regs = {}
    for e in alloc["active"]:
        if e["area"] in cn.REGISTER_AREAS:
            for k in range(e["length"]):
                regs[(e["area"], e["address"] + k)] = e["identity"]
    bit_regs = {(cn.BIT_OVERLAY[e["area"]], e["address"] // 16) for e in alloc["active"] if e["area"] in cn.BIT_AREAS}
    c["bit_blocks_do_not_overlay_registers"] = not (bit_regs & set(regs))
    c["one_codesys_channel_per_register_or_bit"] = len(plan["io_mappings"]) == len(
        {(m["parameter"], m["word_index"], m.get("bit_index")) for m in plan["io_mappings"]})
    res.update(model_pinned=pinned, allocation=[{k: e[k] for k in ("identity", "datatype", "direction", "area",
                                                                    "address", "length", "action")} for e in alloc["active"]],
               project_file=plan["project_file"])


def render_model(model: dict, target_bytes: bytes):
    canon_bytes = (json.dumps(model, indent=2) + "\n").encode("utf-8")
    lt = rg.logic_module()
    return rg.render(canon_bytes, target_bytes, None, [], lt.make_bundle(model))


def cmd_isolation(a, res):
    f = stored(a)
    model = json.loads(f["engineering/model.json"])
    mapping = json.loads(f["engineering/modbus_mapping.json"])
    inst = json.loads(f["engineering/logic_instances.json"])["instances"]
    pid = model["project_id"]
    c = res["checks"]
    by_eq = {}
    for s in mapping["signals"]:
        by_eq.setdefault(s["equipment"], []).append(s)
    c["multiple_equipment_types"] = len({e["type"] for e in model["equipment"]}) >= 2
    c["identities_unique"] = len({s["identity"] for s in mapping["signals"]}) == len(mapping["signals"])
    c["identity_format_project_equipment_tag"] = all(
        s["identity"] == f"{pid}/{s['equipment']}/{s['identity'].split('/', 2)[2]}" for s in mapping["signals"])
    c["plc_symbols_unique"] = len({s["tag"] for s in mapping["signals"]}) == len(mapping["signals"])
    c["variables_owned_by_one_equipment"] = all(v.get("equipment") in {e["id"] for e in model["equipment"]}
                                                for v in model["variables"].values())
    c["template_bindings_stay_inside_equipment"] = all(
        model["variables"][var]["equipment"] == i["equipment"] for i in inst for var in i["bind"].values())
    bound = [var for i in inst for var in i["bind"].values()]
    c["no_variable_driven_by_two_templates"] = len(bound) == len(set(bound))

    target_bytes = Path(a.target).read_bytes()
    ahu = next(e["id"] for e in model["equipment"] if e["type"] == "AHU")
    pump = next(e["id"] for e in model["equipment"] if e["type"] == "PUMP")
    cases = []

    def case(name, mutate, want_status, want_code=None, want_text=None):
        m = copy.deepcopy(model)
        mutate(m)
        validation, files = render_model(m, target_bytes)
        errs = validation["errors"]
        ok = validation["status"] == want_status and (
            want_code is None or any(e["code"] == want_code and (want_text or "") in e["message"] for e in errs))
        extra = {}
        if validation["status"] == "ACCEPTED":
            mp = json.loads(files["engineering/modbus_mapping.json"])
            extra["identities"] = sorted(s["identity"] for s in mp["signals"] if s["identity"].endswith("/Setpoint"))
            ok = ok and len(extra["identities"]) == 2
        cases.append(dict(name=name, status=validation["status"], expected=want_status, expected_code=want_code,
                          errors=errs, passed=ok, **extra))

    def same_tag(m):
        m["variables"]["PUMP01_Setpoint"] = {"type": "REAL", "initial": 1.5, "role": "setpoint", "equipment": pump}
        m["signals"].append({"equipment": pump, "tag": "Setpoint", "symbol": "PUMP01_Setpoint", "datatype": "REAL32",
                             "direction": "READ_WRITE", "modbus": {"area": "HOLDING_REGISTER", "length": 2}})

    def cross_bind(m):
        eq = next(e for e in m["equipment"] if e["id"] == pump)
        eq["logic"].setdefault("bind", {})["StartCommand"] = "StartCommand"

    def dup_symbol(m):
        next(s for s in m["signals"] if s["equipment"] == pump and s["tag"] == "StartCommand")["symbol"] = "FanRunning"

    def wrong_type(m):
        next(e for e in m["equipment"] if e["id"] == pump)["type"] = "AHU"

    def unknown_tpl(m):
        next(e for e in m["equipment"] if e["id"] == pump)["logic"]["template"] = "PUMP_DOES_NOT_EXIST"

    case("same_tag_in_two_equipment_distinct_identities", same_tag, "ACCEPTED")
    case("pump_logic_bound_to_ahu_variable", cross_bind, "REJECTED", "LOGIC_TEMPLATE", "equipment isolation")
    case("duplicate_plc_symbol_across_equipment", dup_symbol, "REJECTED", "DUPLICATE_SYMBOL")
    case("template_for_other_equipment_type", wrong_type, "REJECTED", "LOGIC_TEMPLATE", "is for equipment type PUMP")
    case("unknown_logic_template", unknown_tpl, "REJECTED", "LOGIC_TEMPLATE", "unknown logic template")
    for x in cases:
        c[x["name"]] = x["passed"]
    res.update(equipment={e: sorted(s["identity"] for s in v) for e, v in sorted(by_eq.items())}, cases=cases,
               ahu=ahu, pump=pump)


def cmd_template_equivalence(a, res):
    legacy = rg.render(Path(a.legacy_model).read_bytes(), Path(a.legacy_target).read_bytes(), None, [])[1]
    mt = jload(a.model)
    templ = rg.render(Path(a.model).read_bytes(), Path(a.target).read_bytes(), None, [],
                      rg.logic_module().make_bundle(mt))[1]
    c = res["checks"]
    c["impl_identical"] = legacy["generated/plc/PLC_PRG_impl.st"] == templ["generated/plc/PLC_PRG_impl.st"]
    ld = legacy["generated/plc/PLC_PRG_decl.st"].decode().splitlines()
    td = templ["generated/plc/PLC_PRG_decl.st"].decode().splitlines()
    c["decl_identical_except_title_comment"] = len(ld) == len(td) and [x for x, y in zip(ld, td) if x != y] == [ld[2]]
    la, ta = json.loads(legacy["engineering/allocation.json"]), json.loads(templ["engineering/allocation.json"])
    c["allocation_identical"] = la["active"] == ta["active"] and la["retired"] == ta["retired"]
    lp, tp = json.loads(legacy["engineering/codesys_plan.json"]), json.loads(templ["engineering/codesys_plan.json"])
    strip = lambda p: {k: v for k, v in p.items() if k not in ("project_file", "boot_app_file")}  # noqa: E731
    c["codesys_plan_identical_except_project_name"] = strip(lp) == strip(tp)
    res.update(title_lines=[ld[2], td[2]], project_files=[lp["project_file"], tp["project_file"]],
               impl_sha256=hashlib.sha256(templ["generated/plc/PLC_PRG_impl.st"]).hexdigest())


def cmd_adapter_generic(a, res):
    words = set()
    for m in a.models:
        model = jload(m)
        for e in model["equipment"]:
            words |= {e["id"], e["type"]}
        for s in model["signals"]:
            words |= {s["tag"], rv.symbol(s), rv.plc_var(s)}
        words |= set(model.get("variables") or {})
    words = sorted(w for w in words if w)

    def scan(p: Path) -> list[dict]:
        text = p.read_text(encoding="utf-8", errors="replace")
        return [{"file": p.name, "line": text.count("\n", 0, mt.start()) + 1, "word": w} for w in words
                for mt in re.finditer(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])", text)]

    hits, files = [], {}
    for p in sorted(Path(a.adapter_dir).glob("*.py")):
        files[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
        hits += scan(p)
    control = scan(Path(a.control_file)) if a.control_file else []
    res["checks"]["adapter_scripts_found"] = bool(files)
    res["checks"]["scanner_positive_control_detects_names"] = bool(control)
    res["checks"]["no_equipment_names_in_adapter"] = not hits
    res.update(adapter_files=files, words_checked=len(words), hits=hits, control_file=a.control_file,
               control_hits=len(control))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("validation", "mapping", "isolation", "template-equivalence", "adapter-generic"))
    ap.add_argument("--result", required=True)
    for k in ("eng-root", "gen-root", "target", "legacy-model", "legacy-target", "model", "adapter-dir", "control-file"):
        ap.add_argument("--" + k)
    ap.add_argument("--revision", type=int)
    ap.add_argument("--models", nargs="*", default=[])
    a = ap.parse_args()
    res = {"step": "s2_check_" + a.command, "checks": {}}
    try:
        {"validation": cmd_validation, "mapping": cmd_mapping, "isolation": cmd_isolation,
         "template-equivalence": cmd_template_equivalence, "adapter-generic": cmd_adapter_generic}[a.command](a, res)
        failed = [k for k, v in res["checks"].items() if v is not True]
        ok = bool(res["checks"]) and not failed
        res["operation_status"] = "PASS" if ok else "FAILED"
        res["reason"] = f"{len(res['checks'])} checks passed" if ok else "failed: " + ", ".join(failed)
    except Exception as ex:
        res["operation_status"], res["reason"] = "FAILED", f"{type(ex).__name__}: {ex}"
    Path(a.result).parent.mkdir(parents=True, exist_ok=True)
    Path(a.result).write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(res["operation_status"], res["reason"])
    return 0 if res["operation_status"] == "PASS" else 20


if __name__ == "__main__":
    sys.exit(main())
