import unittest

from odoo.libs.documents.document import Document
from odoo.libs.documents.readers import (
    ANY,
    DATA,
    ROWS,
    TEXT,
    TREE,
    BaseReader,
    get_readers,
    known_readers,
    register_reader,
)


class _Stub(BaseReader):
    def __init__(self, name, mimetypes, yields, value=None, boom=False):
        self.name = name
        self.mimetypes = frozenset(mimetypes)
        self.yields = tuple(yields)
        self._value = value
        self._boom = boom
        self.calls = 0

    def read(self, document):
        self.calls += 1
        if self._boom:
            raise RuntimeError("no")
        return self._value


def _forget(*readers):
    from odoo.libs.documents import readers as module

    for bucket in module._READERS.values():
        for reader in readers:
            while reader in bucket:
                bucket.remove(reader)


class TestRegistry(unittest.TestCase):
    def test_a_reader_must_declare_what_it_yields(self):
        with self.assertRaises(ValueError):
            register_reader(_Stub("x", {"a/b"}, ()))

    def test_a_reader_must_declare_a_mimetype(self):
        with self.assertRaises(ValueError):
            register_reader(_Stub("x", (), (TEXT,)))

    def test_an_unknown_representation_is_refused_at_registration(self):
        with self.assertRaises(ValueError):
            register_reader(_Stub("x", {"a/b"}, ("pixels",)))

    def test_a_reader_must_name_itself(self):
        with self.assertRaises(ValueError):
            register_reader(_Stub("", {"a/b"}, (TEXT,)))

    def test_the_shipped_readers_are_registered(self):
        for name in ("csv", "json", "xml"):
            self.assertIn(name, known_readers())

    def test_a_named_mimetype_is_tried_before_a_fallback(self):
        named = _Stub("named", {"a/b"}, (TEXT,), "named")
        fallback = _Stub("fallback", {ANY}, (TEXT,), "fallback")
        register_reader(fallback)
        register_reader(named)
        try:
            self.assertEqual(
                [r.name for r in get_readers("a/b", TEXT)], ["named", "fallback"]
            )
        finally:
            _forget(named, fallback)

    def test_an_unknown_representation_is_refused_at_lookup(self):
        with self.assertRaises(ValueError):
            get_readers("a/b", "pixels")


class TestDeriving(unittest.TestCase):
    def test_derived_once_and_kept(self):
        reader = _Stub("counting", {"a/b"}, (TEXT,), "hello")
        register_reader(reader)
        try:
            doc = Document(b"...", "a/b", "x")
            self.assertEqual(doc.text, "hello")
            self.assertEqual(doc.text, "hello")
            self.assertEqual(reader.calls, 1)
        finally:
            _forget(reader)

    def test_a_reader_that_raises_lets_the_next_one_answer(self):
        broken = _Stub("broken", {"a/b"}, (TEXT,), boom=True)
        working = _Stub("working", {"a/b"}, (TEXT,), "hello")
        register_reader(broken)
        register_reader(working)
        try:
            self.assertEqual(Document(b"...", "a/b", "x").text, "hello")
            self.assertEqual(broken.calls, 1)
            self.assertEqual(working.calls, 1)
        finally:
            _forget(broken, working)

    def test_nobody_can_read_it(self):
        doc = Document(b"\x00\x01\x02\x03", "application/x-nothing", "x")
        self.assertEqual(doc.text, "")
        self.assertIsNone(doc.tree)
        self.assertFalse(doc.provides(TEXT))


class TestShippedReaders(unittest.TestCase):
    def test_xml_yields_a_tree_even_without_a_prolog(self):
        doc = Document(b"<Invoice><Total>1</Total></Invoice>", name="cfdi.xml")
        self.assertEqual(doc.mimetype, "application/xml")
        self.assertIsNotNone(doc.tree)
        self.assertTrue(doc.provides(TREE))

    def test_a_childless_root_still_counts_as_a_tree(self):
        self.assertTrue(Document(b"<Invoice/>", name="x.xml").provides(TREE))

    def test_json_yields_data(self):
        doc = Document(b'{"total": 12.5}', name="x.json")
        self.assertEqual(doc.data_dict, {"total": 12.5})
        self.assertTrue(doc.provides(DATA))

    def test_csv_yields_rows(self):
        doc = Document(b"name,total\nACME,12\n", name="x.csv")
        self.assertEqual(doc.rows, [["name", "total"], ["ACME", "12"]])
        self.assertTrue(doc.provides(ROWS))

    def test_csv_honours_a_declared_separator(self):
        doc = Document(b"name;total\nACME;12\n", name="x.csv", separator=";")
        self.assertEqual(doc.rows, [["name", "total"], ["ACME", "12"]])

    def test_a_latin1_csv_reads_without_replacement_characters(self):
        doc = Document("name\nCafé Ñoño\n".encode("latin-1"), name="x.csv")
        self.assertEqual(doc.rows, [["name"], ["Café Ñoño"]])

    def test_text_falls_back_to_decoding_when_no_reader_claims_it(self):
        self.assertEqual(
            Document(b"plain words", "text/plain", "x.txt").text, "plain words"
        )


class TestTheAuditFoundThese(unittest.TestCase):
    def test_text_is_clamped_however_it_was_derived(self):
        doc = Document(("x" * 200_000).encode(), "text/plain", "big.txt")
        self.assertEqual(len(doc.text), 60_000)

    def test_a_mimetype_no_reader_claims_still_yields_its_text(self):
        doc = Document(b"a,b\n1,2\n", "application/csv", "x.csv")
        self.assertEqual(doc.text, "a,b\n1,2\n")
        self.assertEqual(doc.rows, [["a", "b"], ["1", "2"]])

    def test_prose_that_opens_with_a_bracket_is_not_xml(self):
        doc = Document(b"<note> this is prose, not markup", "text/plain", "n.txt")
        self.assertEqual(doc.mimetype, "text/plain")
        self.assertTrue(doc.text.startswith("<note>"))

    def test_real_xml_without_a_prolog_is_still_promoted(self):
        doc = Document(b"<Invoice><Total>1</Total></Invoice>", "text/plain", "c.xml")
        self.assertEqual(doc.mimetype, "application/xml")
        self.assertIsNotNone(doc.tree)

    def test_bytes_that_decode_but_are_not_text_yield_none(self):
        for name, data in (
            ("nul and controls", b"\x00\x01\x02\x03"),
            ("whole byte range", bytes(range(256)) * 40),
        ):
            with self.subTest(name=name):
                self.assertEqual(Document(data, "application/x-nothing", name).text, "")

    def test_rows_are_not_bounded_by_the_text_clamp(self):
        source = "col_a,col_b\n" + "".join(f"value{i},{i}\n" for i in range(6000))
        doc = Document(source.encode(), "text/csv", "big.csv")
        self.assertEqual(len(doc.rows), 6001)
        self.assertEqual(doc.rows[-1], ["value5999", "5999"])
        self.assertEqual(len(doc.text), 60_000)

    def test_a_large_json_document_still_parses(self):
        import json as _json

        payload = {f"k{i}": f"v{i}" for i in range(6000)}
        doc = Document(_json.dumps(payload).encode(), "application/json", "big.json")
        rows = doc.data_dict
        assert rows is not None
        self.assertEqual(len(rows), 6000)

    def test_a_large_xml_document_still_parses(self):
        source = ("<r>" + "".join(f"<i>{i}</i>" for i in range(6000)) + "</r>").encode()
        doc = Document(source, "application/xml", "big.xml")
        self.assertEqual(len(doc.tree), 6000)
        self.assertEqual(len(doc.text), 60_000)

    def test_the_clamp_warns_once_per_document_not_once_per_read(self):
        doc = Document(("x" * 200_000).encode(), "text/plain", "big.txt")
        with self.assertLogs("odoo.libs.documents.document", level="WARNING") as caught:
            doc.text
            doc.text
            doc.text
        self.assertEqual(len(caught.records), 1)


class TestDocument(unittest.TestCase):
    def test_empty_data_is_refused(self):
        with self.assertRaises(ValueError):
            Document(b"")

    def test_of_bytes_accepts_base64(self):
        import base64 as b64

        doc = Document.of_bytes(b64.b64encode(b"<a/>").decode(), name="x.xml")
        self.assertIsNotNone(doc.tree)

    def test_an_unknown_representation_is_refused(self):
        with self.assertRaises(ValueError):
            Document(b"x", "text/plain").provides("pixels")
