# -*- coding: utf-8 -*-
"""Limits on the runner process (stemseal/limits.py). These start a small test program, not the cell runner, so that what
is measured is the limit itself. Run: python -m unittest discover -s tests"""
import json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock
os.environ.setdefault("STEMSEAL_HOME", tempfile.mkdtemp(prefix="stemseal_test_"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stemseal import hub, limits

PROGRAM = r'''
import json, os, subprocess, sys, time
op = sys.stdin.read().strip()
if op == "ok": print("ran")
elif op == "memory":
    b = bytearray(1024 * 1024 * 1024); print("allocated")
elif op == "spin":
    while True: pass
elif op == "child":
    subprocess.run([sys.executable, "-c", "pass"]); print("started")
elif op == "child_then_wait":
    try: subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    except Exception: pass
    time.sleep(60)
elif op == "write":
    with open("out.txt", "w") as f: f.write("x" * 100)
    print("wrote")
elif op == "files":
    fs = [open(sys.executable, "rb") for _ in range(40)]; print("opened")
elif op == "priority":
    if os.name == "nt":
        import ctypes
        k = ctypes.WinDLL("kernel32"); k.GetCurrentProcess.restype = ctypes.c_void_p; k.GetPriorityClass.argtypes = [ctypes.c_void_p]
        print(json.dumps({"class": k.GetPriorityClass(k.GetCurrentProcess())}))
    else:
        print(json.dumps({"nice": os.getpriority(os.PRIO_PROCESS, 0)}))
'''
WORK = tempfile.mkdtemp(prefix="stemseal_limits_")
PROG = os.path.join(WORK, "program.py")
with open(PROG, "w", encoding="utf-8") as f: f.write(PROGRAM)
ROOT_USER = os.name == "posix" and os.geteuid() == 0

def run(op, timeout=5):
    return limits.run([sys.executable, "-I", "-B", PROG], op.encode(), timeout, cwd=tempfile.mkdtemp(dir=WORK))

class Limits(unittest.TestCase):
    def test_plain_program_runs(self):
        code, out, _ = run("ok")
        self.assertEqual(code, 0); self.assertIn(b"ran", out)

    @unittest.skipUnless(limits.MEMORY_ENFORCED, "memory limit not enforced on this system")
    def test_memory(self):
        code, out, _ = run("memory")
        self.assertNotEqual(code, 0); self.assertNotIn(b"allocated", out)

    def test_cpu_or_wall_time(self):
        t = time.time()
        try:
            code, out, _ = run("spin", timeout=2)
            self.assertNotEqual(code, 0)
        except limits.Timeout: pass
        self.assertLessEqual(time.time() - t, 2 + 1.5)

    @unittest.skipIf(ROOT_USER, "the process-count limit does not apply to root")
    def test_no_child_process(self):
        code, out, _ = run("child")
        self.assertNotIn(b"started", out)

    def test_nothing_left_after_timeout(self):
        made = []
        real = subprocess.Popen
        def keep(*a, **k):
            p = real(*a, **k); made.append(p); return p
        with mock.patch.object(limits.subprocess, "Popen", side_effect=keep):
            with self.assertRaises(limits.Timeout): run("child_then_wait", timeout=1)
        self.assertEqual(len(made), 1); self.assertIsNotNone(made[0].poll())
        if os.name == "posix":                    # its whole process group is gone (allowing a moment for the system to reap it)
            end = time.time() + 5
            while time.time() < end:
                try: os.killpg(made[0].pid, 0)
                except ProcessLookupError: break
                time.sleep(0.1)
            with self.assertRaises(ProcessLookupError): os.killpg(made[0].pid, 0)

    @unittest.skipIf(os.name == "nt", "file size limit is Linux/macOS")
    def test_no_file_written(self):
        code, out, _ = run("write")
        self.assertNotIn(b"wrote", out)

    @unittest.skipIf(os.name == "nt", "open-file limit is Linux/macOS")
    def test_open_files(self):
        code, out, _ = run("files")
        self.assertNotIn(b"opened", out)

    def test_priority_is_lower(self):
        code, out, _ = run("priority")
        got = json.loads(out.decode())
        if os.name == "nt": self.assertEqual(got["class"], limits._BELOW_NORMAL_PRIORITY_CLASS)
        else: self.assertGreaterEqual(got["nice"], min(19, os.getpriority(os.PRIO_PROCESS, 0) + limits.NICE))

    def test_failure_to_apply_runs_nothing(self):
        if os.name == "nt":
            patch = mock.patch.object(limits, "_assign", return_value=False)
        else:
            def broken(cpu):
                def apply(): raise OSError("no")
                return apply
            patch = mock.patch.object(limits, "_posix_limits", broken)
        with patch:
            with self.assertRaises(limits.LimitError): run("ok")

    def test_environment_can_only_lower(self):
        for v, want in (("1000", 256), ("128", 128), ("0", 256), ("-5", 256), ("abc", 256), ("", 256)):
            with self.subTest(v=v), mock.patch.dict(os.environ, {"STEMSEAL_MEM_MB": v}):
                self.assertEqual(limits.mem_mb(), want)

class Hub(unittest.TestCase):
    def test_cell_call_when_limits_cannot_apply(self):
        with mock.patch.object(limits, "run", side_effect=limits.LimitError("x")):
            r = hub.call("vat_supply_price", {"total": 11000}, caller="t")
            self.assertEqual((r["status"], r["reason"]), ("not_available", "cannot apply limits on this machine"))
            self.assertEqual(hub.purity_check("def cell_executor(input_data):\n    return {}\n"), [hub.LIMITS_FAILED])

    def test_checker_timeout_is_not_a_pass(self):
        with mock.patch.object(limits, "run", side_effect=limits.Timeout()):
            self.assertTrue(hub.purity_check("def cell_executor(input_data):\n    return {}\n"))

    def test_cells_still_answer(self):
        r = hub.call("vat_supply_price", {"total": 11000}, caller="t")
        self.assertEqual(r["status"], "ok"); self.assertEqual(r["result"], {"supply_price": 10000, "vat": 1000})

if __name__ == "__main__":
    unittest.main()
