"""S6 regeneration CLI (CPython, deterministic, no LLM).

canonical revision model + target profile
  -> revision engine (phase0/s6/engine/revision.py: checks, diff, policy, lock-aware allocation)
  -> S3 generator (phase0/s3/generator/generate.py: ST, Modbus mapping, CODESYS plan)
  -> immutable revision store:
       <eng-root>/revisions/rNNN/{model,target,allocation,modbus_mapping,codesys_plan,revision_diff,validation,manifest}.json
       <gen-root>/revisions/rNNN/plc/{PLC_PRG.st, PLC_PRG_decl.st, PLC_PRG_impl.st, PLC_VARIABLES.txt}
       <eng-root>/revisions/rejected/<label>/   (rejected attempts; accepted revisions untouched)
       <eng-root>/revisions/index.json          (append-only history + current pointer)
Revision directories are written once (temp dir + rename) and never modified.

Commands:
  commit    --model M --target T --label L   validate + generate + store (or record rejection)
  dry-run   --model M --target T --label L   same pipeline, written to revisions/attempts/<label>, store untouched
  stage     --revision N --out D             copy stored revision into a deploy stage (adapter layout)
  reproduce --revision N --out D             regenerate N from its stored inputs, compare with the stored artifacts
  rollback  --to N --out D                   reproduce N into a deploy stage and record a rollback event
Common: --eng-root, --gen-root, --result <json>. Exit: 0 PASS/ACCEPTED, 21 REJECTED / not reproducible, 2 store error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / "engine"))
sys.path.insert(0, str(HERE.parents[2] / "s3" / "generator"))
import revision as rv  # noqa: E402
import generate as s3gen  # noqa: E402

cn = rv.cn
LOGIC_DIR = HERE.parents[2] / "s2" / "logic"
DEFAULT_PROJECT_NAME = "AI_BMS_S6_r{revision:03d}"


def logic_module():
    """S2 equipment logic templates; only needed by models that select templates."""
    if str(LOGIC_DIR) not in sys.path:
        sys.path.insert(0, str(LOGIC_DIR))
    import logic_templates
    return logic_templates
ENG_FILES = ("model.json", "target.json", "validation.json", "revision_diff.json", "allocation.json",
             "modbus_mapping.json", "codesys_plan.json")
PLC_FILES = ("PLC_PRG.st", "PLC_PRG_decl.st", "PLC_PRG_impl.st", "PLC_VARIABLES.txt")


def dumps(obj) -> bytes:
    return (json.dumps(obj, indent=2) + "\n").encode("utf-8")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def plc_variables(m3: dict, entries: list[dict], rev: int) -> str:
    where: dict[str, list[str]] = {}
    for e in entries:
        where.setdefault(e["plc_var"], []).append(f"{s3gen.loc(e)} {e['tag']} {e['datatype']} {e['direction']}")
        for b, n in (e.get("bits") or {}).items():
            where.setdefault(n, []).append(f"{s3gen.loc(e)} bit {b} of {e['tag']}")
    lines = [f"# PLC_VARIABLES {m3['model_id']} (revision {rev}) - generated, deterministic",
             "# name : TYPE := initial ; role ; equipment ; modbus"]
    for name in s3gen.declared_variables(m3, entries):
        v = m3["variables"][name]
        lines.append(f"{name} : {v['type']} := {s3gen.literal(v['type'], v['initial'])} ; {v.get('role')} ; "
                     f"{v.get('equipment', '-')} ; {' | '.join(where.get(name, [])) or 'unmapped'}")
    lines.append("# Modbus image variables (bound to Modbus_TCP_Server channels)")
    for e in entries:
        for w in s3gen.image_words(e):
            if w != e["plc_var"]:
                lines.append(f"{w} : {'BOOL' if e['datatype'] == 'BOOL' else 'WORD'} ; image of {e['tag']} ; {s3gen.loc(e)}")
    return "\n".join(lines) + "\n"


def render(canon_bytes: bytes, target_bytes: bytes, parent: dict | None, history: list[dict],
           logic_bytes: bytes | None = None):
    """Pure function: inputs -> (validation dict, {logical path: bytes}). No paths, no timestamps.
    `logic_bytes` = logic template bundle (only for models that select equipment logic templates)."""
    canon = json.loads(canon_bytes.decode("utf-8"))
    target = json.loads(target_bytes.decode("utf-8"))
    out = rv.build(canon, target, parent, history)
    msha, tsha = sha(canon_bytes), sha(target_bytes)
    rev = canon.get("revision")
    lt = bundle = None
    if logic_bytes is not None:
        lt, bundle = logic_module(), json.loads(logic_bytes.decode("utf-8"))
        lerr = lt.check(canon, bundle)
        out["stages"]["logic_template"] = "PASS" if not lerr else "FAILED"
        if lerr:
            out["errors"] = out["errors"] + lerr
            out["status"] = "REJECTED"
    validation = {"schema": "ai_bms.revision_validation.v1", "project_id": canon.get("project_id"),
                  "revision": rev, "parent_revision": canon.get("parent_revision"), "status": out["status"],
                  "stages": out["stages"], "errors": out["errors"], "model_sha256": msha, "target_sha256": tsha}
    if logic_bytes is not None:
        validation["logic_templates_sha256"] = sha(logic_bytes)
    files = {"engineering/model.json": canon_bytes, "engineering/target.json": target_bytes,
             "engineering/validation.json": dumps(validation)}
    if logic_bytes is not None:
        files["engineering/logic_templates.json"] = logic_bytes
    if out["diff"] is not None:
        files["engineering/revision_diff.json"] = dumps(out["diff"])
    if out["status"] != "ACCEPTED":
        return validation, files

    m3, entries, lock = out["model"], out["entries"], out["lock"]
    io = s3gen.channel_mappings(m3, entries)
    if lt is not None:
        title = f"{canon['project_id']}: " + ", ".join(f"{e['id']} ({e.get('type')})" for e in canon["equipment"])
        decl, impl = s3gen.generate_st(m3, entries, logic=lt.render(canon, bundle), title=title)
        files["engineering/logic_instances.json"] = dumps({
            "schema": "ai_bms.logic_instances.v1", "project_id": canon["project_id"], "revision": rev,
            "instances": lt.instances(canon, bundle)})
    else:
        decl, impl = s3gen.generate_st(m3, entries)
    by_sym = {e["symbol"]: e for e in lock["active"]}
    actions = {c["identity"]: c["mapping"]["action"] for c in out["diff"]["changes"] if "mapping" in c}
    mapping = s3gen.mapping_artifact(m3, rv.PROFILE, entries, msha, io)
    mapping.update(schema="ai_bms.modbus_mapping.v1", base_schema=mapping["schema"], project_id=canon["project_id"],
                   revision=rev, parent_revision=canon.get("parent_revision"), target_sha256=tsha)
    for s in mapping["signals"]:
        i = by_sym[s["tag"]]["identity"]
        s["identity"], s["equipment"] = i, i.split("/")[1]
        s["mapping_action"] = actions[i]
    mapped = {e["plc_var"] for e in entries} | {n for e in entries for n in (e.get("bits") or {}).values()}
    mapping["unmapped"] = [{"var": n, "type": m3["variables"][n]["type"], "equipment": m3["variables"][n].get("equipment"),
                            "reason": "PLC variable without a Modbus signal in this revision"}
                           for n in s3gen.declared_variables(m3, entries) if n not in mapped]
    mapping["retired"] = lock["retired"]
    plan = s3gen.codesys_plan(m3, rv.PROFILE, entries, io)
    name = (target.get("artifacts") or {}).get("project_name", DEFAULT_PROJECT_NAME).format(
        revision=rev, project=canon["project_id"].replace("-", "_"))
    plan["project_file"], plan["boot_app_file"] = f"{name}.project", f"{name}.app"
    allocation = {"schema": "ai_bms.allocation_lock.v1", "project_id": canon["project_id"], "revision": rev,
                  "parent_revision": canon.get("parent_revision"), "model_sha256": msha, "target_sha256": tsha,
                  "active": lock["active"], "retired": lock["retired"]}
    files.update({
        "engineering/allocation.json": dumps(allocation),
        "engineering/modbus_mapping.json": dumps(mapping),
        "engineering/codesys_plan.json": dumps(plan),
        "generated/plc/PLC_PRG_decl.st": decl.encode("utf-8"),
        "generated/plc/PLC_PRG_impl.st": impl.encode("utf-8"),
        "generated/plc/PLC_PRG.st": (decl + "\n" + impl).encode("utf-8"),
        "generated/plc/PLC_VARIABLES.txt": plc_variables(m3, entries, rev).encode("utf-8"),
    })
    return validation, files


class StoreError(Exception):
    pass


class Store:
    def __init__(self, eng_root: str, gen_root: str):
        self.eng = Path(eng_root) / "revisions"
        self.gen = Path(gen_root) / "revisions"
        self.index_path = self.eng / "index.json"

    def index(self) -> dict | None:
        return json.loads(self.index_path.read_text(encoding="utf-8")) if self.index_path.exists() else None

    def save_index(self, idx: dict) -> None:
        self.eng.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_bytes(dumps(idx))
        os.replace(tmp, self.index_path)

    def accepted(self) -> list[int]:
        idx = self.index()
        return sorted(r["revision"] for r in idx["revisions"]) if idx else []

    def dirs(self, n: int) -> tuple[Path, Path]:
        return self.eng / f"r{n:03d}", self.gen / f"r{n:03d}"

    def path_of(self, n: int, logical: str) -> Path:
        e, g = self.dirs(n)
        return e / logical.split("/", 1)[1] if logical.startswith("engineering/") else g / logical.split("/", 1)[1]

    def read(self, n: int) -> dict:
        e, _ = self.dirs(n)
        man = json.loads((e / "manifest.json").read_text(encoding="utf-8"))
        files = {}
        for logical, digest in man["files"].items():
            b = self.path_of(n, logical).read_bytes()
            if sha(b) != digest:
                raise StoreError(f"r{n:03d} {logical}: sha256 does not match manifest (revision modified)")
            files[logical] = b
        return files

    def parent_and_history(self, parent_rev, before: int):
        parent = None
        if parent_rev is not None:
            pf = self.read(parent_rev)
            parent = {"model": json.loads(pf["engineering/model.json"]), "lock": json.loads(pf["engineering/allocation.json"])}
        history = []
        for n in self.accepted():
            if n < before:
                history.append({"revision": n, "active": json.loads(self.read(n)["engineering/allocation.json"])["active"]})
        return parent, history

    def write_revision(self, n: int, files: dict) -> dict:
        e, g = self.dirs(n)
        if e.exists() or g.exists():
            raise StoreError(f"revision {n} already exists; revisions are immutable")
        te, tg = e.with_name(f".r{n:03d}.tmp"), g.with_name(f".r{n:03d}.tmp")
        for t in (te, tg):
            if t.exists():
                shutil.rmtree(t)
        manifest = {"schema": "ai_bms.revision_manifest.v1", "revision": n, "files": {}}
        for logical, b in sorted(files.items()):
            dst = (te / logical.split("/", 1)[1]) if logical.startswith("engineering/") else (tg / logical.split("/", 1)[1])
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b)
            manifest["files"][logical] = sha(b)
        (te / "manifest.json").write_bytes(dumps(manifest))
        os.replace(tg, g)
        os.replace(te, e)
        return manifest


def store_errors(store: Store, canon: dict) -> list[dict]:
    idx = store.index()
    rev, parent = canon.get("revision"), canon.get("parent_revision")
    errs = []
    if idx is None:
        if rev != 1 or parent is not None:
            errs.append(rv.err("STORE", "the first revision of a project must be revision 1 with parent_revision null"))
        return errs
    if canon.get("project_id") != idx["project_id"]:
        errs.append(rv.err("STORE", f"project_id {canon.get('project_id')!r} does not match store project {idx['project_id']!r}"))
    acc = store.accepted()
    if isinstance(rev, int) and (rev in acc or store.dirs(rev)[0].exists()):
        errs.append(rv.err("STORE", f"revision {rev} already exists; revisions are immutable"))
    elif rev != max(acc) + 1:
        errs.append(rv.err("STORE", f"revision must be {max(acc) + 1} (got {rev!r})"))
    if parent not in acc:
        errs.append(rv.err("STORE", f"parent_revision {parent!r} is not an accepted revision"))
    return errs


def compare_files(a: dict, b: dict) -> list[str]:
    diffs = []
    for k in sorted(set(a) | set(b)):
        if k not in a or k not in b:
            diffs.append(f"{k}: present in only one side")
        elif k.endswith(".json"):
            if json.loads(a[k]) != json.loads(b[k]):
                diffs.append(f"{k}: semantic difference")
        elif a[k] != b[k]:
            diffs.append(f"{k}: content difference")
    return diffs


def write_stage(files: dict, out: Path) -> list[str]:
    """Deploy-stage layout used by the S1-FIX CODESYS adapter: generated/PLC_PRG_*.st, engineering/*.json."""
    if (out / "engineering" / "codesys_plan.json").exists():
        raise StoreError(f"stage {out} already populated (no silent overwrite)")
    written = []
    for logical, b in sorted(files.items()):
        name = logical.split("/")[-1]
        dst = out / ("generated" if logical.startswith("generated/") else "engineering") / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b)
        written.append(str(dst))
    return written


def cmd_commit(a, store: Store, dry: bool) -> dict:
    canon_bytes, target_bytes = Path(a.model).read_bytes(), Path(a.target).read_bytes()
    try:
        canon = json.loads(canon_bytes.decode("utf-8"))
    except ValueError as ex:
        canon = {}
        validation, files = {"status": "REJECTED", "errors": [rv.err("SCHEMA", f"model is not valid JSON: {ex}")]}, \
            {"engineering/model.json": canon_bytes}
    else:
        serr = [] if dry else store_errors(store, canon)
        if serr:
            validation = {"schema": "ai_bms.revision_validation.v1", "project_id": canon.get("project_id"),
                          "revision": canon.get("revision"), "parent_revision": canon.get("parent_revision"),
                          "status": "REJECTED", "stages": {"store": "FAILED"}, "errors": serr,
                          "model_sha256": sha(canon_bytes), "target_sha256": sha(target_bytes)}
            files = {"engineering/model.json": canon_bytes, "engineering/target.json": target_bytes,
                     "engineering/validation.json": dumps(validation)}
        else:
            p = canon.get("parent_revision") if canon.get("parent_revision") in store.accepted() else None
            before = canon["revision"] if isinstance(canon.get("revision"), int) else 10 ** 9
            parent, history = store.parent_and_history(p, before)
            logic_bytes = logic_module().make_bundle(canon) if any(
                isinstance(e, dict) and isinstance(e.get("logic"), dict) for e in canon.get("equipment") or []) else None
            validation, files = render(canon_bytes, target_bytes, parent, history, logic_bytes)
    res = {"step": "regenerate_" + ("dry_run" if dry else "commit"), "label": a.label,
           "revision": canon.get("revision"), "parent_revision": canon.get("parent_revision"),
           "status": validation["status"], "errors": validation["errors"]}
    if dry or validation["status"] != "ACCEPTED":
        sub = "attempts" if dry else "rejected"
        d = store.eng / sub / a.label
        if d.exists():
            raise StoreError(f"{sub}/{a.label} already exists")
        for logical, b in sorted(files.items()):
            dst = d / logical.replace("engineering/", "").replace("generated/plc/", "plc/")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b)
        res["attempt_dir"] = str(d)
        if not dry:
            idx = store.index()
            if idx is not None:
                idx["rejected"].append({"label": a.label, "revision": canon.get("revision"),
                                        "parent_revision": canon.get("parent_revision"),
                                        "codes": sorted({e["code"] for e in validation["errors"]})})
                idx["events"].append({"event": "reject", "label": a.label})
                store.save_index(idx)
    else:
        manifest = store.write_revision(canon["revision"], files)
        idx = store.index() or {"schema": "ai_bms.revision_index.v1", "project_id": canon["project_id"],
                                "revisions": [], "rejected": [], "current": None, "events": []}
        idx["revisions"].append({"revision": canon["revision"], "parent_revision": canon.get("parent_revision"),
                                 "label": a.label, "model_sha256": sha(canon_bytes), "status": "ACCEPTED",
                                 "manifest_sha256": sha(dumps(manifest))})
        idx["current"] = canon["revision"]
        idx["events"].append({"event": "commit", "revision": canon["revision"], "label": a.label})
        store.save_index(idx)
        res["revision_dirs"] = [str(x) for x in store.dirs(canon["revision"])]
        res["manifest"] = manifest
    if "engineering/revision_diff.json" in files:
        res["diff_summary"] = json.loads(files["engineering/revision_diff.json"])["summary"]
    accepted = validation["status"] == "ACCEPTED"
    res["operation_status"] = "PASS" if accepted else "REJECTED"
    res["reason"] = (("dry-run accepted (store untouched)" if dry else f"revision {canon['revision']} accepted and stored")
                     if accepted else "rejected: " + "; ".join(f"{e['code']}: {e['message']}" for e in validation["errors"])[:600])
    return res


def reproduce(store: Store, n: int) -> tuple[dict, dict, list[str]]:
    stored = store.read(n)
    canon = json.loads(stored["engineering/model.json"])
    parent, history = store.parent_and_history(canon.get("parent_revision"), n)
    validation, files = render(stored["engineering/model.json"], stored["engineering/target.json"], parent, history,
                               stored.get("engineering/logic_templates.json"))
    return stored, files, compare_files(stored, files)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("commit", "dry-run", "stage", "reproduce", "rollback"))
    ap.add_argument("--eng-root", required=True)
    ap.add_argument("--gen-root", required=True)
    ap.add_argument("--model")
    ap.add_argument("--target")
    ap.add_argument("--label")
    ap.add_argument("--revision", type=int)
    ap.add_argument("--to", type=int)
    ap.add_argument("--out")
    ap.add_argument("--result")
    a = ap.parse_args()
    store = Store(a.eng_root, a.gen_root)
    try:
        if a.command in ("commit", "dry-run"):
            res = cmd_commit(a, store, a.command == "dry-run")
        elif a.command == "stage":
            files = store.read(a.revision)
            res = {"step": "stage", "revision": a.revision, "written": write_stage(files, Path(a.out)),
                   "operation_status": "PASS", "reason": f"r{a.revision:03d} staged (manifest verified)"}
        else:
            n = a.revision if a.command == "reproduce" else a.to
            stored, files, diffs = reproduce(store, n)
            res = {"step": a.command, "revision": n, "reproducible": not diffs, "differences": diffs,
                   "files_compared": sorted(stored)}
            if a.out and not diffs:
                res["written"] = write_stage(files, Path(a.out))
            if a.command == "rollback" and not diffs:
                idx = store.index()
                idx["events"].append({"event": "rollback", "from": idx["current"], "to": n})
                idx["current"] = n
                store.save_index(idx)
            res["operation_status"] = "PASS" if not diffs else "FAILED"
            res["reason"] = (f"r{n:03d} regenerated from stored inputs; all {len(stored)} artifacts semantically identical"
                             if not diffs else "regenerated artifacts differ: " + "; ".join(diffs))
    except StoreError as ex:
        res = {"step": a.command, "operation_status": "FAILED", "reason": f"store error: {ex}"}
    if a.result:
        Path(a.result).parent.mkdir(parents=True, exist_ok=True)
        Path(a.result).write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(res["operation_status"], res["reason"])
    return {"PASS": 0, "REJECTED": 21}.get(res["operation_status"], 2 if "store error" in res["reason"] else 21)


if __name__ == "__main__":
    sys.exit(main())
