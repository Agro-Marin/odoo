"""Nothing in the registry may be chosen by module load order.

`get_readers` orders by cost, and `Document._derive` falls through a reader that
answered nothing to the next one. Both of those decide between readers that
differ. Neither decides between two readers that claim the same mimetype for the
same representation at the same cost: there `sorted` is stable, so the winner is
whichever module imported first, and no module declares that.

This is not hypothetical. `document_extract` reads a PDF's text with pymupdf and
`attachment_indexation` reads the same mimetype with pdfminer.six, and the two
agree on tokens but not on line structure. Registering the second would have
made every database's `index_content` depend on its module graph. It was caught
by hand; this is what catches the next one.

Tagged `post_install` deliberately. The registry fills as modules import, so an
at-install run would assert over whichever part of the graph happened to be
loaded and pass by seeing less.
"""

from collections import defaultdict

from odoo.libs.documents import (
    TEXT,
    BaseReader,
    register_reader,
    registered_readers,
    registered_writers,
    unregister_reader,
)
from odoo.tests.common import BaseCase, tagged


def reader_claims(readers):
    """Every (mimetype, representation, cost) more than one reader answers for."""
    claims = defaultdict(list)
    for reader in readers:
        for mimetype in reader.mimetypes:
            for representation in reader.yields:
                claims[(mimetype, representation, reader.cost)].append(reader.name)
    return {key: names for key, names in claims.items() if len(names) > 1}


def writer_claims(writers):
    claims = defaultdict(list)
    for writer in writers:
        claims[(writer.mimetype, writer.consumes)].append(writer.name)
    return {key: names for key, names in claims.items() if len(names) > 1}


@tagged("post_install", "-at_install")
class TestRegistryIsUnambiguous(BaseCase):
    def test_no_two_readers_claim_one_mimetype_at_one_cost(self):
        ambiguous = reader_claims(registered_readers())

        self.assertFalse(
            ambiguous,
            "these readers are chosen by module load order:\n  "
            + "\n  ".join(
                f"{mimetype} {representation} at cost {cost}: "
                + ", ".join(sorted(names))
                for (mimetype, representation, cost), names in sorted(ambiguous.items())
            )
            + "\nGive one of them a higher cost, or decide which owns the format.",
        )

    def test_no_two_writers_claim_one_mimetype(self):
        """The writer side has neither of the reader side's protections.

        A writer declares no cost, `get_writers` sorts by nothing, and
        `Document.of` takes the first that claims the mimetype -- with no
        fall-through, because a writer that cannot write has no way to say so.
        So a writer collision is decided by load order with nothing to soften
        it, which is why the same invariant is asserted here rather than left
        for the reader half to imply.
        """
        ambiguous = writer_claims(registered_writers())

        self.assertFalse(
            ambiguous,
            "these writers are chosen by module load order:\n  "
            + "\n  ".join(
                f"{mimetype} from {representation}: " + ", ".join(sorted(names))
                for (mimetype, representation), names in sorted(ambiguous.items())
            ),
        )

    def test_the_check_is_not_looking_at_an_empty_registry(self):
        """A registry the test cannot see is a green assertion about nothing.

        The library's own six are a floor that holds in any install; this
        module's `pdf_text` proves the enumeration reaches past the library into
        the addon the test ships in, which a count alone would not.
        """
        self.assertGreaterEqual(len(registered_readers()), 6)
        self.assertGreaterEqual(len(registered_writers()), 6)
        self.assertIn("pdf_text", [r.name for r in registered_readers()])

    def test_a_collision_is_actually_detected(self):
        """The two assertions above are green, and green is what a broken check
        also looks like. This registers the collision they exist to find --
        pymupdf's mimetype and cost, claimed twice -- and asserts it is
        reported, so neither can rot into passing over nothing."""
        clash = type(
            "_Pdfminer",
            (BaseReader,),
            {
                "name": "test_second_pdf_text",
                "mimetypes": frozenset({"application/pdf"}),
                "yields": (TEXT,),
                "cost": 0,
                "read": lambda self, document: "",
            },
        )()
        register_reader(clash)
        self.addCleanup(unregister_reader, clash)

        found = reader_claims(registered_readers())

        self.assertIn(("application/pdf", TEXT, 0), found)
        self.assertIn("test_second_pdf_text", found[("application/pdf", TEXT, 0)])
        self.assertIn("pdf_text", found[("application/pdf", TEXT, 0)])
