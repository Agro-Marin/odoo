import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odoo.libs import hashing

_VECTORS = {
    0: "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262",
    1: "2d3adedff11b61f14c886e35afa036736dcd87a74d27b5c1510225d0f592e213",
    1024: "42214739f095a406f3fc83deb889744ac00df831c10daa55189b5d121c855af7",
}


def _vector_input(length):
    return bytes(i % 251 for i in range(length))


class TestBlake3Path(unittest.TestCase):
    def setUp(self):
        if not hashing.HAS_BLAKE3:
            self.skipTest("blake3 extension not installed")

    def test_known_vectors(self):
        for length, expected in _VECTORS.items():
            with self.subTest(length=length):
                self.assertEqual(hashing.content_hash(_vector_input(length)), expected)

    def test_content_and_cache_agree(self):
        data = b"the quick brown fox"
        self.assertEqual(hashing.content_hash(data), hashing.cache_hash(data))

    def test_tag_and_length(self):
        self.assertEqual(hashing.ALGO_TAG, "b3")
        self.assertEqual(hashing.CONTENT_DIGEST_LEN, 64)
        self.assertEqual(len(hashing.content_hash(b"x")), 64)

    def test_persisted_digests_always_fit_the_column(self):
        self.assertLessEqual(hashing.CONTENT_DIGEST_LEN, hashing.CONTENT_DIGEST_MAX_LEN)
        for length in (40, 64):
            self.assertLessEqual(length, hashing.CONTENT_DIGEST_MAX_LEN)

    def test_column_is_sized_from_the_invariant_not_the_algorithm(self):
        from odoo.addons.base.models.ir_attachment import IrAttachment

        self.assertEqual(IrAttachment.checksum.size, hashing.CONTENT_DIGEST_MAX_LEN)

    def test_multithreaded_matches_single(self):
        big = b"z" * (2 * hashing._MT_MIN_BYTES)
        self.assertGreater(len(big), hashing._MT_MIN_BYTES)
        hasher = hashing.content_hasher()
        hasher.update(big)
        self.assertEqual(hashing.content_hash(big), hasher.hexdigest())


class TestFallbackPath(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(hashing, "HAS_BLAKE3", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_content_falls_back_to_sha1(self):
        data = b"attachment payload"
        self.assertEqual(
            hashing.content_hash(data),
            hashlib.sha1(data, usedforsecurity=False).hexdigest(),
        )

    def test_cache_falls_back_to_sha256(self):
        data = b"canonical json bytes"
        self.assertEqual(hashing.cache_hash(data), hashlib.sha256(data).hexdigest())

    def test_hashers_fall_back_too(self):
        self.assertEqual(hashing.content_hasher().name, "sha1")
        self.assertEqual(hashing.cache_hasher().name, "sha256")

    def test_empty_content_has_a_digest(self):
        self.assertEqual(
            hashing.content_hash(b""),
            hashlib.sha1(b"", usedforsecurity=False).hexdigest(),
        )


class TestIncrementalEquivalence(unittest.TestCase):
    def _all_forms(self, data):
        one_shot = hashing.content_hash(data)
        hasher = hashing.content_hasher()
        for i in range(0, len(data), 7):
            hasher.update(data[i : i + 7])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payload"
            path.write_bytes(data)
            from_file = hashing.content_hash_file(path)
            fed = hashing.content_hasher()
            hashing.update_from_file(fed, path)
        return one_shot, hasher.hexdigest(), from_file, fed.hexdigest()

    def _assert_all_equal(self, data):
        one_shot, incremental, from_file, fed = self._all_forms(data)
        self.assertEqual(incremental, one_shot)
        self.assertEqual(from_file, one_shot)
        self.assertEqual(fed, one_shot)

    def test_equivalence(self):
        for label, data in (
            ("empty", b""),
            ("short", b"hello"),
            ("multichunk", bytes(range(256)) * 500),
        ):
            with self.subTest(payload=label):
                self._assert_all_equal(data)

    def test_equivalence_on_fallback(self):
        with mock.patch.object(hashing, "HAS_BLAKE3", False):
            self._assert_all_equal(bytes(range(256)) * 500)

    def test_interleaved_update_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part"
            path.write_bytes(b"middle")
            mixed = hashing.cache_hasher()
            mixed.update(b"before")
            hashing.update_from_file(mixed, path)
            mixed.update(b"after")
        self.assertEqual(mixed.hexdigest(), hashing.cache_hash(b"beforemiddleafter"))
