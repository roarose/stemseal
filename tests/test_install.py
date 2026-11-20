# -*- coding: utf-8 -*-
"""The runner starts in the three ways people install stemseal: a venv, `pip install --user`, and `uvx`.
Slow (it installs the package), so it runs only with STEMSEAL_INSTALL_TESTS=1 (the CI install job sets it)."""
import json, os, shutil, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALL = ["call", "vat_supply_price", json.dumps({"total": 11000})]
WANT = {"supply_price": 10000, "vat": 1000}

def bin_dir(prefix): return os.path.join(prefix, "Scripts" if os.name == "nt" else "bin")
def exe(d, name): return os.path.join(d, name + (".exe" if os.name == "nt" else ""))

@unittest.skipUnless(os.environ.get("STEMSEAL_INSTALL_TESTS") == "1", "set STEMSEAL_INSTALL_TESTS=1")
class Install(unittest.TestCase):
    def env(self, **kw):
        e = dict(os.environ, STEMSEAL_HOME=tempfile.mkdtemp(prefix="stemseal_home_")); e.update(kw); return e

    def check_call(self, cmd, env):
        p = subprocess.run(cmd + CALL, capture_output=True, timeout=300, env=env, cwd=tempfile.mkdtemp())
        self.assertEqual(p.returncode, 0, p.stdout.decode() + p.stderr.decode())
        out = json.loads(p.stdout.decode())
        self.assertEqual(out["status"], "ok"); self.assertEqual(out["result"], WANT)

    def test_venv(self):
        d = tempfile.mkdtemp(prefix="stemseal_venv_")
        subprocess.run([sys.executable, "-m", "venv", d], check=True, timeout=300)
        subprocess.run([exe(bin_dir(d), "python"), "-m", "pip", "install", "-q", ROOT], check=True, timeout=600)
        self.check_call([exe(bin_dir(d), "stemseal")], self.env())

    def test_pip_user(self):
        base = tempfile.mkdtemp(prefix="stemseal_user_")
        env = self.env(PYTHONUSERBASE=base, PIP_BREAK_SYSTEM_PACKAGES="1")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--user", ROOT], check=True, timeout=600, env=env)
        scripts = [os.path.join(r, f) for r, _, fs in os.walk(base) for f in fs if f in ("stemseal", "stemseal.exe")]
        self.assertTrue(scripts, "no stemseal script under %s" % base)
        self.check_call([scripts[0]], env)

    @unittest.skipUnless(shutil.which("uvx"), "uvx not installed")
    def test_uvx(self):
        self.check_call(["uvx", "--no-cache", "--from", ROOT, "stemseal"], self.env())

if __name__ == "__main__":
    unittest.main()
