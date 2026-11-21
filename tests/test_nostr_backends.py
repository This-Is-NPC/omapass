"""The npub is derived only by well-known packages, never by a module named nak."""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from tests.sandbox_env import sandbox_only
from tests.helper_loader import HELPER_PATH, ROOT, load_helper


class TestNostrBackends(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def test_a_module_named_nak_is_never_imported_or_given_the_key(self) -> None:
        fake = types.ModuleType("nak")
        fake.PrivateKey = mock.Mock(name="PrivateKey")
        with mock.patch.dict(sys.modules, {"nak": fake, "coincurve": None, "secp256k1": None}):
            self.assertIsNone(self.mod.has_nostr_crypto())
            self.assertIsNone(self.mod.npub_from_sk(b"\x01" * 32))
        fake.PrivateKey.assert_not_called()

    def test_the_backends_are_the_two_known_packages(self) -> None:
        seen = []
        real_import = __import__

        def spy(name, *a, **kw):
            if name in ("coincurve", "nak", "secp256k1"):
                seen.append(name)
                raise ImportError(name)
            return real_import(name, *a, **kw)

        with mock.patch("builtins.__import__", side_effect=spy):
            self.mod.has_nostr_crypto()
        self.assertEqual(seen, ["coincurve", "secp256k1"])

    def test_no_text_tells_the_user_to_install_nak(self) -> None:
        for path in (HELPER_PATH, ROOT / "README.md"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("import nak", text)
                self.assertNotIn("nak.PrivateKey", text)
                self.assertNotIn(", nak,", text)
                self.assertNotIn("install nak", text)


# BIP-340 test vectors: secret key -> x-only public key.
KNOWN_KEYS = {
    1: "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798",
    3: "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
}


@sandbox_only
class TestRealBackend(unittest.TestCase):
    """npub derivation against the real secp256k1 library in the image."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def test_a_real_backend_is_installed(self) -> None:
        self.assertEqual(self.mod.has_nostr_crypto(), "coincurve")

    def test_known_secret_keys_give_the_known_npub(self) -> None:
        for n, pub in KNOWN_KEYS.items():
            with self.subTest(sk=n):
                npub = self.mod.npub_from_sk(n.to_bytes(32, "big"))
                self.assertTrue(npub.startswith("npub1"), npub)
                hrp, data = self.mod.bech32_decode(npub)
                self.assertEqual(hrp, "npub")
                self.assertEqual(bytes(self.mod.convertbits(data, 5, 8, False)).hex(), pub)

    def test_generated_nsec_and_npub_belong_together(self) -> None:
        nsec, npub = self.mod.generate_nsec_material()
        sk = self.mod.parse_nostr_secret(nsec)
        self.assertEqual(self.mod.npub_from_sk(sk), npub)


if __name__ == "__main__":
    unittest.main()
