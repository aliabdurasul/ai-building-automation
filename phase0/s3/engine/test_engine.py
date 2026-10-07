"""S3 engine self-tests: validator rejections, allocator determinism, codec round-trips.

Run: python -m unittest phase0/s3/engine/test_engine.py   (or python test_engine.py)
"""
from __future__ import annotations

import copy
import json
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import canonical as cn  # noqa: E402

MODEL = json.loads((HERE.parent / "model" / "s3_model.json").read_text(encoding="utf-8"))


def with_signals(sigs, profile="t"):
    m = copy.deepcopy(MODEL)
    for s in sigs:
        s.setdefault("profiles", [profile])
    m["signals"] = sigs
    return m


def sig(tag, dt, direction, area, **mb):
    return {"tag": tag, "datatype": dt, "direction": direction, "modbus": {"area": area, **mb}}


class Validator(unittest.TestCase):
    def assertInvalid(self, sigs, fragment):
        errs = cn.validate(with_signals(sigs), "t")
        self.assertTrue(any(fragment in e for e in errs), f"expected {fragment!r} in {errs}")

    def test_real_profiles_valid(self):
        for p in ("types", "ahu"):
            self.assertEqual(cn.validate(MODEL, p), [], p)

    def test_bool_in_input_register(self):
        self.assertInvalid([sig("B", "BOOL", "READ", "INPUT_REGISTER")], "BOOL in INPUT_REGISTER is invalid")

    def test_real32_length_1(self):
        self.assertInvalid([sig("R", "REAL32", "READ", "INPUT_REGISTER", length=1)], "REAL32 requires length=2")

    def test_real32_length_2_valid(self):
        self.assertEqual(cn.validate(with_signals([sig("R", "REAL32", "READ", "INPUT_REGISTER", length=2)]), "t"), [])

    def test_uint16_int16_length_1_valid(self):
        m = with_signals([sig("U", "UINT16", "READ", "INPUT_REGISTER", length=1),
                          sig("I", "INT16", "READ", "INPUT_REGISTER", length=1)])
        self.assertEqual(cn.validate(m, "t"), [])

    def test_duplicate_address(self):
        self.assertInvalid([sig("A", "UINT16", "READ", "INPUT_REGISTER", address=3),
                            sig("B", "INT16", "READ", "INPUT_REGISTER", address=3)], "overlaps")

    def test_overlapping_real32(self):
        self.assertInvalid([sig("A", "REAL32", "READ", "INPUT_REGISTER", address=2),
                            sig("B", "REAL32", "READ", "INPUT_REGISTER", address=3)], "overlaps")

    def test_missing_datatype(self):
        self.assertInvalid([{"tag": "X", "direction": "READ", "modbus": {"area": "INPUT_REGISTER"}}], "missing datatype")

    def test_missing_area(self):
        self.assertInvalid([{"tag": "X", "datatype": "INT16", "direction": "READ", "modbus": {}}], "missing area")

    def test_missing_direction(self):
        self.assertInvalid([{"tag": "X", "datatype": "INT16", "modbus": {"area": "INPUT_REGISTER"}}], "direction")

    def test_read_in_holding(self):
        self.assertInvalid([sig("X", "INT16", "READ", "HOLDING_REGISTER")], "READ (PLC->client)")

    def test_write_in_input_register(self):
        self.assertInvalid([sig("X", "INT16", "WRITE", "INPUT_REGISTER")], "client-writable")

    def test_word_in_coil(self):
        self.assertInvalid([sig("X", "WORD", "WRITE", "COIL")], "cannot live in bit area")

    def test_byte_order_in_model_rejected(self):
        self.assertInvalid([sig("R", "REAL32", "READ", "INPUT_REGISTER", byte_order="ABCD")], "must not be set in the model")

    def test_capacity(self):
        sigs = [sig(f"R{i}", "REAL32", "READ", "INPUT_REGISTER") for i in range(6)]
        self.assertInvalid(sigs, "no 2 free register(s)")

    def test_address_beyond_capacity(self):
        self.assertInvalid([sig("R", "REAL32", "READ", "INPUT_REGISTER", address=9)], "exceeds INPUT_REGISTER capacity")

    def test_coil_overlaying_used_register(self):
        self.assertInvalid([sig("W", "UINT16", "WRITE", "HOLDING_REGISTER", address=0),
                            sig("C", "BOOL", "WRITE", "COIL", address=3)], "overlays HOLDING_REGISTER 0")

    def test_scale_on_real_rejected(self):
        self.assertInvalid([sig("R", "REAL32", "READ", "INPUT_REGISTER", scale=0.1)], "scale is only supported")

    def test_duplicate_tag(self):
        self.assertInvalid([sig("A", "INT16", "READ", "INPUT_REGISTER"), sig("A", "UINT16", "READ", "INPUT_REGISTER")],
                           "duplicate tag")


class Allocator(unittest.TestCase):
    def test_deterministic_and_order_independent(self):
        for p in ("types", "ahu"):
            ref = cn.allocate(MODEL, p)
            for seed in range(20):
                m = copy.deepcopy(MODEL)
                random.Random(seed).shuffle(m["signals"])
                self.assertEqual(cn.allocate(m, p), ref, f"{p} seed {seed}")

    def test_pinned_s1_words_kept(self):
        for p in ("types", "ahu"):
            by = {e["tag"]: e for e in cn.allocate(MODEL, p)}
            self.assertEqual((by["Command"]["area"], by["Command"]["address"]), ("HOLDING_REGISTER", 0))
            self.assertEqual((by["Status"]["area"], by["Status"]["address"]), ("INPUT_REGISTER", 0))

    def test_bit_blocks_from_top(self):
        by = {e["tag"]: e for e in cn.allocate(MODEL, "types")}
        self.assertEqual(by["TestCoil"]["overlay"]["register"], 9)
        self.assertEqual(by["TestDiscreteInput"]["overlay"]["register"], 9)

    def test_example_from_spec(self):
        m = with_signals([sig("FanRunning", "BOOL", "READ", "DISCRETE_INPUT"),
                          sig("FanSpeed", "INT16", "READ", "INPUT_REGISTER"),
                          sig("SupplyTemp", "REAL32", "READ", "INPUT_REGISTER"),
                          sig("Setpoint", "REAL32", "READ_WRITE", "HOLDING_REGISTER")])
        a = [(e["tag"], e["area"], e["address"], e["length"]) for e in cn.allocate(m, "t")]
        self.assertEqual(a, [("Setpoint", "HOLDING_REGISTER", 0, 2), ("FanSpeed", "INPUT_REGISTER", 0, 1),
                             ("SupplyTemp", "INPUT_REGISTER", 1, 2), ("FanRunning", "DISCRETE_INPUT", 144, 1)])


class Codec(unittest.TestCase):
    def test_real32_roundtrip_all_orderings(self):
        for o in cn.ORDERINGS:
            for v in (21.5, 22.0, 18.25, 123.456, -3.75):
                self.assertEqual(cn.decode_real32(cn.encode_real32(v, o), o), cn.f32(v))

    def test_orderings_distinguishable(self):
        for o in cn.ORDERINGS:
            self.assertEqual(cn.matching_orderings(cn.encode_real32(123.456, o), 123.456), [o])

    def test_int16(self):
        self.assertEqual(cn.encode_int16(-1234), 64302)
        self.assertEqual(cn.decode_int16(64302), -1234)
        self.assertEqual(cn.decode_int16(1234), 1234)
        self.assertEqual(cn.decode_int16(0x8000), -32768)


def run_to_file(path: str) -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    names = sorted(t.id().split(".", 1)[1] for t in _iter(suite))
    r = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    ok = r.wasSuccessful()
    out = {"step": "engine_selftest", "tests_run": r.testsRun, "failures": len(r.failures), "errors": len(r.errors),
           "tests": names, "operation_status": "PASS" if ok else "FAILED",
           "reason": "%d engine tests passed (validator, allocator, codec)" % r.testsRun if ok else "engine tests failed"}
    Path(path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0 if ok else 20


def _iter(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _iter(t)
        else:
            yield t


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--result":
        sys.exit(run_to_file(sys.argv[2]))
    unittest.main(verbosity=2)
