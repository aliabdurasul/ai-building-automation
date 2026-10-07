"""S3 canonical Modbus type & mapping engine (CPython, deterministic, no LLM).

canonical signals -> validate -> allocate (stable addresses) -> resolved mapping entries.

Platform facts (register capacity, coil/discrete-input bit overlay) come from the model's
`platform` section, which records values measured on the CODESYS ModbusTCP Server Device
(see docs/phase0/S3_REPORT.md, discovery). Byte/word order is NOT a model input: it is a
measurement output written by the verifier.
"""
from __future__ import annotations

import math
import struct

DATATYPES = {
    "BOOL":   {"plc_type": "BOOL", "registers": 0, "signedness": "n/a"},
    "WORD":   {"plc_type": "WORD", "registers": 1, "signedness": "unsigned (bit field)"},
    "INT16":  {"plc_type": "INT",  "registers": 1, "signedness": "signed (two's complement)"},
    "UINT16": {"plc_type": "UINT", "registers": 1, "signedness": "unsigned"},
    "REAL32": {"plc_type": "REAL", "registers": 2, "signedness": "IEEE 754 binary32"},
}
REGISTER_AREAS = ("HOLDING_REGISTER", "INPUT_REGISTER")
BIT_AREAS = ("COIL", "DISCRETE_INPUT")
AREAS = REGISTER_AREAS + BIT_AREAS
DIRECTIONS = ("READ", "WRITE", "READ_WRITE")
BIT_OVERLAY = {"COIL": "HOLDING_REGISTER", "DISCRETE_INPUT": "INPUT_REGISTER"}
CLIENT_WRITABLE = {"HOLDING_REGISTER", "COIL"}
FUNCTIONS = {
    "HOLDING_REGISTER": {"read": "FC3", "write": "FC6/FC16"},
    "INPUT_REGISTER": {"read": "FC4", "write": None},
    "COIL": {"read": "FC1", "write": "FC5/FC15"},
    "DISCRETE_INPUT": {"read": "FC2", "write": None},
}
ORDER_INPUT_KEYS = ("byte_order", "word_order", "register_order")


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def signals_for(model: dict, profile: str) -> list[dict]:
    return [s for s in model["signals"] if profile in s.get("profiles", [])]


def _len_for(dt: str) -> int:
    return 1 if dt == "BOOL" else DATATYPES[dt]["registers"]


def validate(model: dict, profile: str) -> list[str]:
    """Structural + semantic rules; all must pass before any CODESYS generation."""
    errors: list[str] = []
    plat = model.get("platform", {})
    cap = plat.get("register_capacity", {})
    variables = model.get("variables", {})
    sigs = signals_for(model, profile)
    if not sigs:
        errors.append(f"profile {profile!r} selects no signals")
    tags, plc_vars = set(), set()
    for i, s in enumerate(sigs):
        where = s.get("tag") or f"signal[{i}]"
        mb = s.get("modbus") or {}
        dt, area, direction = s.get("datatype"), mb.get("area"), s.get("direction")
        if not s.get("tag"):
            errors.append(f"{where}: missing tag")
        elif s["tag"] in tags:
            errors.append(f"{where}: duplicate tag")
        tags.add(s.get("tag"))
        if dt is None:
            errors.append(f"{where}: missing datatype")
            continue
        if dt not in DATATYPES:
            errors.append(f"{where}: unsupported datatype {dt}")
            continue
        if area is None:
            errors.append(f"{where}: missing area")
            continue
        if area not in AREAS:
            errors.append(f"{where}: unsupported area {area}")
            continue
        if direction not in DIRECTIONS:
            errors.append(f"{where}: missing/unsupported direction {direction!r}")
            continue
        for k in ORDER_INPUT_KEYS:
            if k in mb:
                errors.append(f"{where}: {k} must not be set in the model (it is measured by verification)")
        pv = s.get("plc_var", s.get("tag"))
        if pv in plc_vars:
            errors.append(f"{where}: plc_var {pv} used by two signals")
        plc_vars.add(pv)
        if pv in variables and variables[pv]["type"] != DATATYPES[dt]["plc_type"]:
            errors.append(f"{where}: plc_var {pv} is {variables[pv]['type']} in the model, datatype {dt} needs {DATATYPES[dt]['plc_type']}")

        if dt == "BOOL" and area in REGISTER_AREAS:
            errors.append(f"{where}: BOOL in {area} is invalid; use COIL/DISCRETE_INPUT or a WORD signal with packed bits")
        if dt != "BOOL" and area in BIT_AREAS:
            errors.append(f"{where}: {dt} cannot live in bit area {area}")
        if direction == "READ" and area in CLIENT_WRITABLE:
            errors.append(f"{where}: READ (PLC->client) signal must use INPUT_REGISTER/DISCRETE_INPUT, not {area}")
        if direction in ("WRITE", "READ_WRITE") and area not in CLIENT_WRITABLE:
            errors.append(f"{where}: {direction} signal needs a client-writable area (HOLDING_REGISTER/COIL), not {area}")

        need = _len_for(dt)
        if "length" in mb and mb["length"] != need:
            errors.append(f"{where}: {dt} requires length={need}, model has length={mb['length']}")
        scale = mb.get("scale", 1.0)
        if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not math.isfinite(scale) or scale <= 0:
            errors.append(f"{where}: scale must be a positive finite number")
        elif scale != 1.0 and dt not in ("INT16", "UINT16"):
            errors.append(f"{where}: scale is only supported for INT16/UINT16 (got {scale} on {dt})")

        if "address" in mb:
            a = mb["address"]
            if not isinstance(a, int) or isinstance(a, bool) or a < 0:
                errors.append(f"{where}: address must be a non-negative integer")
            else:
                limit = cap.get(BIT_OVERLAY.get(area, area), 0) * (16 if area in BIT_AREAS else 1)
                if a + need > limit:
                    errors.append(f"{where}: address {a} (+{need}) exceeds {area} capacity {limit}")

        bits = s.get("bits")
        if bits is not None:
            if dt != "WORD":
                errors.append(f"{where}: packed bits are only allowed on WORD signals")
            seen_bits = set()
            for b, name in bits.items():
                if not str(b).isdigit() or not 0 <= int(b) < 16:
                    errors.append(f"{where}: bit {b} out of range 0..15")
                if name in seen_bits:
                    errors.append(f"{where}: BOOL {name} packed twice")
                seen_bits.add(name)
                if name not in variables:
                    errors.append(f"{where}: bit {b} references unknown variable {name}")
                elif variables[name]["type"] != "BOOL":
                    errors.append(f"{where}: bit {b} variable {name} is {variables[name]['type']}, only BOOL can be packed")
    if not errors:
        try:
            allocate(model, profile)
        except ValidationError as ex:
            errors.extend(ex.errors)
    return errors


def allocate(model: dict, profile: str) -> list[dict]:
    """Deterministic address allocation.

    1. Pinned register addresses, then pinned bit addresses (a bit claims its overlay register).
    2. Unpinned register signals sorted by tag, each at the lowest run of `length` free registers.
    3. Bit areas overlay the register area (COIL->HOLDING, DISCRETE_INPUT->INPUT). Unpinned bit signals
       get whole 16-bit blocks taken from the highest free registers downward, filled by tag order.
    Result order: (area, address, tag). Independent of the signal list order.
    """
    errors: list[str] = []
    cap = model["platform"]["register_capacity"]
    sigs = sorted(signals_for(model, profile), key=lambda s: s["tag"])
    used = {a: [None] * cap[a] for a in REGISTER_AREAS}
    out = {}

    def place(area, start, n, tag):
        if start + n > len(used[area]):
            errors.append(f"{tag}: {area} {start}..{start + n - 1} exceeds capacity {len(used[area])}")
            return False
        clash = {used[area][r] for r in range(start, start + n) if used[area][r] is not None}
        if clash:
            errors.append(f"{tag}: {area} {start}..{start + n - 1} overlaps {sorted(clash)}")
            return False
        for r in range(start, start + n):
            used[area][r] = tag
        return True

    reg_sigs = [s for s in sigs if s["modbus"]["area"] in REGISTER_AREAS]
    for s in [x for x in reg_sigs if "address" in x["modbus"]]:
        area, n, addr = s["modbus"]["area"], _len_for(s["datatype"]), s["modbus"]["address"]
        if place(area, addr, n, s["tag"]):
            out[s["tag"]] = {"address": addr, "length": n, "allocation": "pinned"}

    # Pinned bits claim their overlay register before any register is auto-allocated.
    taken = {a: set() for a in BIT_AREAS}
    for bit_area in BIT_AREAS:
        reg_area = BIT_OVERLAY[bit_area]
        for s in [x for x in sigs if x["modbus"]["area"] == bit_area and "address" in x["modbus"]]:
            a = s["modbus"]["address"]
            reg = a // 16
            owner = used[reg_area][reg] if reg < len(used[reg_area]) else None
            if a in taken[bit_area]:
                errors.append(f"{s['tag']}: duplicate {bit_area} address {a}")
            elif owner is not None and owner != f"<bits:{bit_area}>":
                errors.append(f"{s['tag']}: {bit_area} {a} overlays {reg_area} {reg} used by {owner}")
            else:
                used[reg_area][reg] = f"<bits:{bit_area}>"
                taken[bit_area].add(a)
                out[s["tag"]] = {"address": a, "length": 1, "allocation": "pinned"}

    for s in [x for x in reg_sigs if "address" not in x["modbus"]]:
        area, n = s["modbus"]["area"], _len_for(s["datatype"])
        for addr in range(cap[area] - n + 1):
            if all(used[area][r] is None for r in range(addr, addr + n)):
                place(area, addr, n, s["tag"])
                out[s["tag"]] = {"address": addr, "length": n, "allocation": "auto"}
                break
        else:
            errors.append(f"{s['tag']}: no {n} free register(s) left in {area} (capacity {cap[area]})")

    for bit_area in BIT_AREAS:
        reg_area = BIT_OVERLAY[bit_area]
        auto = [s for s in sigs if s["modbus"]["area"] == bit_area and "address" not in s["modbus"]]
        taken_here = taken[bit_area]
        free_bits = []
        for reg in range(len(used[reg_area]) - 1, -1, -1):
            if len(free_bits) >= len(auto):
                break
            if used[reg_area][reg] is None or used[reg_area][reg] == f"<bits:{bit_area}>":
                used[reg_area][reg] = f"<bits:{bit_area}>"
                free_bits += [reg * 16 + k for k in range(16) if reg * 16 + k not in taken_here]
        if len(free_bits) < len(auto):
            errors.append(f"{bit_area}: not enough free {reg_area} registers for {len(auto)} bit signal(s)")
        for s, a in zip(auto, sorted(free_bits)):
            out[s["tag"]] = {"address": a, "length": 1, "allocation": "auto"}
    if errors:
        raise ValidationError(errors)

    resolved = []
    for s in sigs:
        mb = s["modbus"]
        dt, area = s["datatype"], mb["area"]
        a = out[s["tag"]]
        entry = {
            "tag": s["tag"],
            "plc_var": s.get("plc_var", s["tag"]),
            "datatype": dt,
            "plc_type": DATATYPES[dt]["plc_type"],
            "direction": s["direction"],
            "area": area,
            "address": a["address"],
            "length": a["length"],
            "allocation": a["allocation"],
            "signedness": DATATYPES[dt]["signedness"],
            "scale": float(mb.get("scale", 1.0)),
            "function_read": FUNCTIONS[area]["read"],
            "function_write": FUNCTIONS[area]["write"] if s["direction"] != "READ" else None,
        }
        if area in REGISTER_AREAS:
            entry["registers"] = list(range(a["address"], a["address"] + a["length"]))
        else:
            reg_area = BIT_OVERLAY[area]
            entry["overlay"] = {"register_area": reg_area, "register": a["address"] // 16,
                                "plc_bit": plc_bit_for(model, a["address"])}
        if s.get("bits"):
            entry["bits"] = {str(b): n for b, n in sorted(s["bits"].items(), key=lambda kv: int(kv[0]))}
        if "initial" in s:
            entry["initial"] = s["initial"]
        resolved.append(entry)
    resolved.sort(key=lambda e: (AREAS.index(e["area"]), e["address"], e["tag"]))
    return resolved


def plc_bit_for(model: dict, bit_address: int) -> int:
    """Bit channel index inside the overlaid PLC WORD for a coil/discrete-input address.
    The offset is the measured platform fact `bit_overlay.plc_bit_offset` (8 on this target)."""
    off = model["platform"]["bit_overlay"]["plc_bit_offset"]
    return ((bit_address % 16) + off) % 16


# ---------------- codec (client side) ----------------

ORDERINGS = {
    # name: (description, function regs[2] -> 4 IEEE bytes big-endian A B C D)
    "ABCD": "register[n]=high word, big-endian bytes in each register",
    "CDAB": "register[n]=low word, big-endian bytes in each register",
    "BADC": "register[n]=high word, bytes swapped in each register",
    "DCBA": "register[n]=low word, bytes swapped in each register",
}


def _swap16(v: int) -> int:
    return ((v & 0xFF) << 8) | (v >> 8)


def regs_to_ieee_bytes(regs: list[int], ordering: str) -> bytes:
    r0, r1 = regs
    if ordering in ("BADC", "DCBA"):
        r0, r1 = _swap16(r0), _swap16(r1)
    hi, lo = (r0, r1) if ordering in ("ABCD", "BADC") else (r1, r0)
    return struct.pack(">HH", hi, lo)


def ieee_bytes_to_regs(b: bytes, ordering: str) -> list[int]:
    hi, lo = struct.unpack(">HH", b)
    r0, r1 = (hi, lo) if ordering in ("ABCD", "BADC") else (lo, hi)
    if ordering in ("BADC", "DCBA"):
        r0, r1 = _swap16(r0), _swap16(r1)
    return [r0, r1]


def f32(x: float) -> float:
    return struct.unpack(">f", struct.pack(">f", float(x)))[0]


def f32_bits(x: float) -> int:
    return struct.unpack(">I", struct.pack(">f", float(x)))[0]


def decode_real32(regs: list[int], ordering: str) -> float:
    return struct.unpack(">f", regs_to_ieee_bytes(regs, ordering))[0]


def encode_real32(value: float, ordering: str) -> list[int]:
    return ieee_bytes_to_regs(struct.pack(">f", float(value)), ordering)


def decode_int16(raw: int) -> int:
    return raw - 0x10000 if raw & 0x8000 else raw


def encode_int16(value: int) -> int:
    if not -32768 <= value <= 32767:
        raise ValueError(f"INT16 out of range: {value}")
    return value & 0xFFFF


def matching_orderings(regs: list[int], expected: float) -> list[str]:
    want = f32_bits(expected)
    return [o for o in ORDERINGS if struct.unpack(">I", regs_to_ieee_bytes(regs, o))[0] == want]


def describe_ordering(o: str) -> dict:
    return {
        "name": o,
        "registers_per_value": 2,
        "word_order": "high word first (lower address = most significant 16 bits)" if o in ("ABCD", "BADC")
                      else "low word first (lower address = least significant 16 bits)",
        "byte_order": "big-endian within each register (Modbus standard)" if o in ("ABCD", "CDAB")
                      else "byte-swapped within each register",
        "register_order": ORDERINGS[o],
    }
