# -*- coding: utf-8 -*-
"""The release signer (tools/signer/signer.py) makes keys that stemseal accepts, and its signature passes stemseal's check.
Needs the `cryptography` package, which only the signing PC has; skipped elsewhere. Keys live in a temporary folder only.
Run: python -m unittest discover -s tests"""
import io, json, os, sys, tempfile, unittest
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
        with redirect_stdout(io.StringIO()):
            pubs = signer.make_keys(a, b, passphrase=b"twelve chars ok", allow_fixed=True)
            self.assertEqual(signer.make_keys(a, b, passphrase=b"twelve chars ok", allow_fixed=True), 1)   # never overwrites
        rel = os.path.join(out, "release.json")
        with open(rel, "wb") as f: f.write(json.dumps({"format": 2, "release": 1, "cells": {"x_cell": {"1.0": {}}}}).encode())
        with redirect_stdout(io.StringIO()):
            sig_path = signer.sign(rel, key_path=os.path.join(b, signer.SPARE_NAME), passphrase=b"twelve chars ok", out_dir=out, confirm=False)
            self.assertEqual(signer.sign(rel, key_path=os.path.join(a, signer.MAIN_NAME), passphrase=b"wrong passphrase", out_dir=out, confirm=False), 1)
        with open(rel, "rb") as f: raw = f.read()
        with open(sig_path, "rb") as f: sig = f.read()
        keys = [bytes.fromhex(p) for p in pubs]
        self.assertTrue(update.signed_by_release_key(raw, sig, keys))
        self.assertFalse(update.signed_by_release_key(raw + b" ", sig, keys))
        for d in (a, b):
            with open(os.path.join(d, os.listdir(d)[0]), "rb") as f: self.assertIn(b"ENCRYPTED", f.read())
