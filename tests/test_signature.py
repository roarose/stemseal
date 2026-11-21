# -*- coding: utf-8 -*-
"""Ed25519 (stemseal/ed25519.py) against the RFC 8032 test vectors, and how a release signature file is read.
Run: python -m unittest discover -s tests"""
import os, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stemseal import ed25519, update

# RFC 8032, section 7.1: secret key, public key, message, signature
VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60", "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb", "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7", "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]

class Vectors(unittest.TestCase):
    def test_rfc8032(self):
        for sk, pk, msg, sig in VECTORS:
            sk, pk, msg, sig = map(bytes.fromhex, (sk, pk, msg, sig))
            with self.subTest(pk=pk.hex()[:8]):
                self.assertEqual(ed25519.public_key(sk), pk); self.assertEqual(ed25519.sign(sk, msg), sig)
                self.assertTrue(ed25519.verify(pk, msg, sig))
                self.assertFalse(ed25519.verify(pk, msg + b"\0", sig))
                bad = bytearray(sig); bad[5] ^= 1; self.assertFalse(ed25519.verify(pk, msg, bytes(bad)))
                bad = bytearray(sig); bad[40] ^= 1; self.assertFalse(ed25519.verify(pk, msg, bytes(bad)))

    def test_malformed_input_is_false_not_an_error(self):
        pk = bytes.fromhex(VECTORS[0][1]); sig = bytes.fromhex(VECTORS[0][3])
        for a, s in ((pk[:31], sig), (pk, sig[:63]), (b"\xff" * 32, sig), (pk, sig[:32] + b"\xff" * 32), ("x", sig), (pk, None)):
            self.assertFalse(ed25519.verify(a, b"", s))

    def test_round_trip_and_wrong_key(self):
        for i in range(5):
            sk, other = os.urandom(32), os.urandom(32); msg = os.urandom(i * 50)
            sig = ed25519.sign(sk, msg)
            self.assertTrue(ed25519.verify(ed25519.public_key(sk), msg, sig))
            self.assertFalse(ed25519.verify(ed25519.public_key(other), msg, sig))

    def test_a_release_sized_check_takes_under_a_second(self):
        sk = os.urandom(32); msg = b"x" * (1024 * 1024); sig = ed25519.sign(sk, msg)
        t = time.time(); self.assertTrue(ed25519.verify(ed25519.public_key(sk), msg, sig)); self.assertLess(time.time() - t, 1.0)

class SignatureFile(unittest.TestCase):
    def test_forms(self):
        sk = os.urandom(32); pk = ed25519.public_key(sk); msg = b"release"; sig = ed25519.sign(sk, msg)
        for form in (sig, sig.hex().encode(), sig.hex().upper().encode(), (sig.hex()[:64] + "\r\n" + sig.hex()[64:] + "\n").encode()):
            self.assertTrue(update.signed_by_release_key(msg, form, [pk]))
        for form in (b"", sig[:63], sig.hex()[:-2].encode(), b"z" * 128, sig + b"\n"):
            self.assertFalse(update.signed_by_release_key(msg, form, [pk]))
        self.assertFalse(update.signed_by_release_key(msg, sig, []))

if __name__ == "__main__":
    unittest.main()
