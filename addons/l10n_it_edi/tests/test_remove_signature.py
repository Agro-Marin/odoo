from pathlib import Path

from lxml import etree

from odoo.tests import BaseCase, tagged

from odoo.addons.l10n_it_edi.tools.remove_signature import (
    remove_signature,
    remove_signature_cms,
    remove_signature_fallback,
)

FIXTURES = Path(__file__).parent / "import_xmls"

# A conforming envelope, and one from Servizio Elettrico Nazionale that no
# conforming parser accepts.
CONFORMING = "IT01234567890_FPR01.xml.p7m"
MALFORMED = "IT09633951000_NpFwF.xml.p7m"


class _Target:
    """Stand-in for the record remove_signature() records its strategy on."""
    remove_signature_method = None


@tagged("post_install_l10n", "post_install", "-at_install")
class TestRemoveSignature(BaseCase):
    """ remove_signature() tries each strategy under a try/except, so a strategy
        that cannot run at all is indistinguishable from one that declined --
        which is how the previous OpenSSL implementation went on raising
        AttributeError from its first line without failing a test. Every
        strategy is therefore also called DIRECTLY here, where nothing swallows
        the exception.
    """

    def _fixture(self, name):
        return (FIXTURES / name).read_bytes()

    def test_conforming_envelope_is_unwrapped_by_the_cms_strategy(self):
        """The primary strategy must actually run, not raise into the fallback."""
        content = self._fixture(CONFORMING)

        # Direct call: no try/except in the way.
        extracted = remove_signature_cms(content)
        self.assertTrue(extracted.startswith(b"<?xml"))

        # And it is the strategy remove_signature() ends up using.
        target = _Target()
        self.assertEqual(remove_signature(content, target=target), extracted)
        self.assertEqual(target.remove_signature_method, "remove_signature_cms")

    def test_conforming_envelope_yields_exactly_the_content(self):
        """CMS returns the encapsulated content and nothing else, so the result
           is a standalone document a strict parser accepts."""
        extracted = remove_signature_cms(self._fixture(CONFORMING))
        tree = etree.fromstring(extracted, etree.XMLParser(resolve_entities=False))
        self.assertEqual(etree.QName(tree).localname, "FatturaElettronica")

    def test_malformed_envelope_falls_back(self):
        """The fallback exists for envelopes CMS cannot parse. Keep both halves
           of that pinned: that CMS really does reject this file, and that the
           fallback really does recover the invoice from it."""
        content = self._fixture(MALFORMED)
        with self.assertRaises(ValueError):
            remove_signature_cms(content)

        extracted = remove_signature_fallback(content)
        self.assertIn(b"<p:FatturaElettronica", extracted)
        self.assertIn(b"</p:FatturaElettronica>", extracted)

        target = _Target()
        self.assertEqual(remove_signature(content, target=target), extracted)
        self.assertEqual(target.remove_signature_method, "remove_signature_fallback")

        # The fallback returns a superset of the content -- here the certificate
        # DER trails the closing tag -- so only a recovering parser gets a tree
        # out of it. account_move passes recover=True for this reason.
        tree = etree.fromstring(extracted, etree.XMLParser(recover=True, resolve_entities=False))
        self.assertEqual(etree.QName(tree).localname, "FatturaElettronica")

    def test_content_that_is_not_an_envelope_returns_none(self):
        """No strategy applies, and nothing raises out of remove_signature()."""
        self.assertIsNone(remove_signature(b"<?xml version='1.0'?><invoice/>"))
        self.assertIsNone(remove_signature(b""))

    def test_detached_signature_is_rejected(self):
        """An envelope with no encapsulated content must not read as an empty
           invoice: asn1crypto returns None for it and CMS has to say so."""
        from asn1crypto import cms

        detached = cms.ContentInfo({
            "content_type": "signed_data",
            "content": cms.SignedData({
                "version": "v1",
                "digest_algorithms": [],
                "encap_content_info": {"content_type": "data"},
                "signer_infos": [],
            }),
        }).dump()

        with self.assertRaises(ValueError):
            remove_signature_cms(detached)
