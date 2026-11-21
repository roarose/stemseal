# -*- coding: utf-8 -*-
"""The release signer (tools/signer/signer.py) makes keys that stemseal accepts, and its signature passes stemseal's check.
Needs the `cryptography` package, which only the signing PC has; skipped elsewhere. Keys live in a temporary folder only.
Run: python -m unittest discover -s tests"""
import glob, hashlib, io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools", "signer"))
from stemseal import ed25519, update
try:
    import cryptography  # noqa: F401
    import signer
except ImportError: signer = None

@unittest.skipIf(signer is None, "cryptography is not installed (only the signing PC needs it)")
class Signer(unittest.TestCase):
    def test_keys_sign_and_verify(self):
        a, b, out = (tempfile.mkdtemp() for _ in range(3))
        pw = [b"main passphrase 12", b"spare passphrase 34"]
        with redirect_stdout(io.StringIO()):
            pubs = signer.make_keys(a, b, passphrase=pw, allow_fixed=True)
            self.assertEqual(signer.make_keys(a, b, passphrase=pw, allow_fixed=True), 1)   # never overwrites
        rel = os.path.join(out, "release.json")
        with open(rel, "wb") as f: f.write(json.dumps({"format": 2, "release": 1, "cells": {"x_cell": {"1.0": {}}}}).encode())
        with open(rel, "rb") as f: raw = f.read()
        trusted = json.dumps({"1": hashlib.sha256(raw).hexdigest()}).encode()
        with redirect_stdout(io.StringIO()):
            sig_path = signer.sign(rel, key_path=os.path.join(b, signer.SPARE_NAME), passphrase=pw[1], out_dir=out, confirm=False, trusted=trusted)
            main_sig = signer.sign(rel, key_path=os.path.join(a, signer.MAIN_NAME), passphrase=pw[0], out_dir=tempfile.mkdtemp(), confirm=False, trusted=trusted)
            self.assertEqual(signer.sign(rel, key_path=os.path.join(a, signer.MAIN_NAME), passphrase=pw[1], out_dir=out, confirm=False, trusted=trusted), 1)
            self.assertEqual(signer.sign(rel, key_path=os.path.join(a, signer.MAIN_NAME), passphrase=pw[0], out_dir=out, confirm=False,
                                         trusted=json.dumps({"1": "0" * 64}).encode()), 1)        # not the release the commit lists
        gone = os.path.join(out, "gone.json")
        with open(gone, "wb") as f: f.write(json.dumps({"format": 2, "release": 2, "cells": {}, "revoked_keys": [pubs[0]]}).encode())
        with open(gone, "rb") as f: graw = f.read()
        shown = io.StringIO()
        with redirect_stdout(shown):
            signer.sign(gone, key_path=os.path.join(b, signer.SPARE_NAME), passphrase=pw[1], out_dir=tempfile.mkdtemp(), confirm=False,
                        trusted=json.dumps({"2": hashlib.sha256(graw).hexdigest()}).encode())
        self.assertIn(pubs[0][:16], shown.getvalue())                    # the key a release withdraws is shown before signing
        for path in (sig_path, main_sig):
            with open(path, "rb") as f: sig = f.read()
            keys = [bytes.fromhex(p) for p in pubs]
            self.assertTrue(update.signed_by_release_key(raw, sig, keys))
            self.assertFalse(update.signed_by_release_key(raw + b" ", sig, keys))
        for d in (a, b):
            with open(os.path.join(d, os.listdir(d)[0]), "rb") as f: self.assertIn(b"ENCRYPTED", f.read())

    def test_runs_isolated(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "signer", "signer.py")], capture_output=True)
        self.assertEqual(r.returncode, 2); self.assertIn(b"make-keys", r.stdout)
        for bat in glob.glob(os.path.join(ROOT, "tools", "signer", "*.bat")):
            with open(bat, "rb") as f: self.assertIn(b"python -I ", f.read())

    @unittest.skipUnless(os.name == "nt", "drive types are a Windows matter")
    def test_drive_type_is_read(self):
        self.assertIn(signer._removable(tempfile.gettempdir()), (True, False))
