import base64
import datetime
import hashlib
import io
import logging

from asn1crypto import algos, cms, core, x509

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
    from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        load_pem_private_key,
    )
    from cryptography.x509 import Certificate, load_pem_x509_certificate
except ImportError:
    hashes = None
    PrivateKeyTypes = None
    Encoding = None
    load_pem_private_key = None
    ec = None
    ed25519 = None
    padding = None
    rsa = None
    Certificate = None
    load_pem_x509_certificate = None

from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

from odoo.tools.pdf import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    PdfReader,
    PdfWriter,
    create_string_object,
)
from odoo.tools.pdf import (
    DecodedStreamObject as StreamObject,
)

if TYPE_CHECKING:
    from odoo.addons.base.models.res_company import ResCompany
    from odoo.addons.base.models.res_users import ResUsers

_logger = logging.getLogger(__name__)

#: Characters that terminate or nest a PDF literal string (PDF 32000-1 §7.3.4.2).
_PDF_LITERAL_ESCAPES = str.maketrans({"\\": r"\\", "(": r"\(", ")": r"\)"})


def _escape_pdf_literal(text: str) -> str:
    r"""Escape *text* for inclusion in a PDF literal string ``(...)``.

    ``(``, ``)`` and ``\`` are the delimiters of a literal string, so text
    interpolated into one without escaping does not stay text: an unescaped
    ``)`` ends the string and everything after it is parsed as content-stream
    operators.  Since the only values interpolated here are a signer's name and
    email — which end users control — that turns a display field into control
    over what the visible signature draws.

    Escaping is enough on its own; nothing else in the appearance stream comes
    from user input.  Non-printables are left alone: a PDF literal may contain
    arbitrary bytes, and mangling them would silently corrupt legitimate names.
    """
    return text.translate(_PDF_LITERAL_ESCAPES)


class _SignatureAlgorithm(NamedTuple):
    """CMS algorithm identifiers (asn1crypto names) and signer for one key type."""

    digest: str
    signature: str
    sign: Callable[[bytes], bytes]


class PdfSigner:
    """Add a signature field and a cryptographic signature to a PDF document.

    This implementation follows the Adobe PDF Reference (v1.7) (https://ia601001.us.archive.org/1/items/pdf1.7/pdf_reference_1-7.pdf)
    for the structure of the PDF document,
    and Digital Signatures in a PDF (https://www.adobe.com/devnet-docs/acrobatetk/tools/DigSig/Acrobat_DigitalSignatures_in_PDF.pdf),
    for the structure of the signature in a PDF.
    """

    _CONTENTS_PLACEHOLDER_BYTES = 8192

    def __init__(
        self,
        stream: io.BytesIO,
        company: ResCompany | None = None,
        signing_time=None,
    ) -> None:
        self.signing_time = signing_time
        self.company = company
        if "clone_document_from_reader" not in dir(PdfWriter):
            _logger.info("PDF signature is supported by Python 3.12 and above")
            return
        reader = PdfReader(stream)
        self.writer = PdfWriter()
        self.writer.clone_document_from_reader(reader)

    def sign_pdf(
        self,
        visible_signature: bool = False,
        field_name: str = "Odoo Signature",
        signer: ResUsers | None = None,
    ) -> io.BytesIO | None:
        """Sign the PDF document.

        :return: the resulting output stream, or None in case of error.
        :rtype: io.BytesIO | None
        """
        if not self.company or not load_pem_x509_certificate:
            return None

        _dummy, sig_field_value = self._setup_form(
            visible_signature, field_name, signer
        )

        if not self._perform_signature(sig_field_value):
            return None

        out_stream = io.BytesIO()
        self.writer.write_stream(out_stream)
        return out_stream

    def _load_key_and_certificate(
        self,
    ) -> tuple[PrivateKeyTypes | None, Certificate | None]:
        """Load the private key and certificate.

        :return: a (private key, certificate) tuple, or (None, None) if they couldn't be loaded.
        :rtype: tuple[PrivateKeyTypes | None, Certificate | None]
        """
        if (
            "signing_certificate_id" not in self.company._fields
            or not self.company.signing_certificate_id.pem_certificate
        ):
            return None, None

        certificate = self.company.signing_certificate_id
        cert_bytes = base64.decodebytes(certificate.pem_certificate)
        private_key_bytes = base64.decodebytes(certificate.private_key_id.content)
        return load_pem_private_key(private_key_bytes, None), load_pem_x509_certificate(
            cert_bytes
        )

    def _setup_form(
        self,
        visible_signature: bool,
        field_name: str,
        signer: ResUsers | None = None,
    ) -> tuple[DictionaryObject, DictionaryObject] | None:
        """Create the /AcroForm and populate it with the signature field.

        :param visible_signature: whether the signature should be visible on the document.
        :param field_name: the name of the signature field.
        :param signer: user shown in the visuals of the signature field.
        :return: a (signature field, signature field value) tuple.
        :rtype: tuple[DictionaryObject, DictionaryObject]
        """
        if "/AcroForm" not in self.writer._root_object:
            form = DictionaryObject()
            form.update({NameObject("/SigFlags"): NumberObject(3)})
            form_ref = self.writer._add_object(form)

            self.writer._root_object.update({NameObject("/AcroForm"): form_ref})
        else:
            form = self.writer._root_object["/AcroForm"].get_object()

            form.update({NameObject("/SigFlags"): NumberObject(3)})

        page = self.writer.pages[0]

        signature_field = DictionaryObject()

        signature_field.update(
            {
                NameObject("/FT"): NameObject("/Sig"),
                NameObject("/T"): create_string_object(field_name),
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/F"): NumberObject(132),
                NameObject("/P"): page.indirect_reference,
            }
        )

        if visible_signature:
            origin = page.mediabox.upper_right
            rect_size = (200, 20)
            padding = 5

            rect = [
                origin[0] - rect_size[0] - padding,
                origin[1] - rect_size[1] - padding,
                origin[0] - padding,
                origin[1] - padding,
            ]

            stream = StreamObject()
            stream.update(
                {
                    NameObject("/BBox"): self._create_number_array_object(
                        [0, 0, rect_size[0], rect_size[1]]
                    ),
                    NameObject("/Resources"): DictionaryObject(
                        {
                            NameObject("/Font"): DictionaryObject(
                                {
                                    NameObject("/F1"): DictionaryObject(
                                        {
                                            NameObject("/Type"): NameObject("/Font"),
                                            NameObject("/Subtype"): NameObject(
                                                "/Type1"
                                            ),
                                            NameObject("/BaseFont"): NameObject(
                                                "/Helvetica"
                                            ),
                                        }
                                    )
                                }
                            )
                        }
                    ),
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Form"),
                }
            )

            content = "Digitally signed"
            if signer is not None:
                content = f"{content} by {signer.name} <{signer.email}>"

            # The text goes into a PDF literal string, so it must be escaped
            # here: create_string_object returns a str subclass and would
            # interpolate the signer's name verbatim.  See _escape_pdf_literal.
            stream._data = (
                f"q 0.5 0 0 0.5 0 0 cm BT /F1 12 Tf 0 TL 0 10 Td "
                f"({_escape_pdf_literal(content)}) Tj ET Q"
            ).encode()
            signature_appearence = DictionaryObject()
            signature_appearence.update({NameObject("/N"): stream})
            signature_field.update(
                {
                    NameObject("/AP"): signature_appearence,
                }
            )
        else:
            rect = [0, 0, 0, 0]

        signature_field.update(
            {NameObject("/Rect"): self._create_number_array_object(rect)}
        )

        signature_field_value = DictionaryObject()
        signature_field_value.update(
            {
                NameObject("/Contents"): ByteStringObject(
                    b"\0" * self._CONTENTS_PLACEHOLDER_BYTES
                ),
                NameObject("/ByteRange"): self._create_number_array_object(
                    [0, 0, 0, 0]
                ),
                NameObject("/Type"): NameObject("/Sig"),
                NameObject("/Filter"): NameObject("/Adobe.PPKLite"),
                NameObject("/SubFilter"): NameObject("/adbe.pkcs7.detached"),
                NameObject("/M"): create_string_object(
                    (self.signing_time or datetime.datetime.now(datetime.UTC)).strftime(
                        "D:%Y%m%d%H%M%S"
                    )
                ),
            }
        )

        signature_field_ref = self.writer._add_object(signature_field)
        signature_field_value_ref = self.writer._add_object(signature_field_value)

        signature_field.update({NameObject("/V"): signature_field_value_ref})

        if "/Fields" not in self.writer._root_object:
            fields = ArrayObject()
        else:
            fields = self.writer._root_object["/Fields"].get_object()
        fields.append(signature_field_ref)
        form.update({NameObject("/Fields"): fields})

        if "/Annots" not in page:
            page[NameObject("/Annots")] = ArrayObject()
        page[NameObject("/Annots")].append(signature_field_ref)

        return signature_field, signature_field_value

    def _get_signature_algorithm(
        self, private_key: PrivateKeyTypes
    ) -> _SignatureAlgorithm | None:
        """Map the private key type to its CMS algorithms and signing callable.

        :return: the matching :class:`_SignatureAlgorithm`, or None for an
            unsupported key type.
        :rtype: _SignatureAlgorithm | None
        """
        if isinstance(private_key, rsa.RSAPrivateKey):
            return _SignatureAlgorithm(
                "sha256",
                "sha256_rsa",
                lambda data: private_key.sign(
                    data, padding.PKCS1v15(), hashes.SHA256()
                ),
            )
        if isinstance(private_key, ec.EllipticCurvePrivateKey):
            return _SignatureAlgorithm(
                "sha256",
                "sha256_ecdsa",
                lambda data: private_key.sign(data, ec.ECDSA(hashes.SHA256())),
            )
        if isinstance(private_key, ed25519.Ed25519PrivateKey):
            return _SignatureAlgorithm("sha512", "ed25519", private_key.sign)
        return None

    def _get_cms_object(
        self,
        digest: bytes,
        certificate: Certificate,
        algorithm: _SignatureAlgorithm,
    ) -> cms.ContentInfo:
        """Create an object that follows the Cryptographic Message Syntax (CMS).

        RFC: https://datatracker.ietf.org/doc/html/rfc5652

        :param digest: the digest of the document in bytes, computed with
            ``algorithm.digest``.
        :param certificate: the signing certificate.
        :param algorithm: the CMS algorithms and signer for the private key.
        :return: a CMS object containing the signature information.
        :rtype: cms.ContentInfo
        """
        cert = x509.Certificate.load(certificate.public_bytes(encoding=Encoding.DER))
        encap_content_info = {"content_type": "data", "content": None}

        attrs = cms.CMSAttributes(
            [
                cms.CMSAttribute({"type": "content_type", "values": ["data"]}),
                cms.CMSAttribute(
                    {
                        "type": "signing_time",
                        "values": [
                            cms.Time(
                                {
                                    "utc_time": core.UTCTime(
                                        self.signing_time
                                        or datetime.datetime.now(datetime.UTC)
                                    )
                                }
                            )
                        ],
                    }
                ),
                cms.CMSAttribute(
                    {
                        "type": "cms_algorithm_protection",
                        "values": [
                            cms.CMSAlgorithmProtection(
                                {
                                    "mac_algorithm": None,
                                    "digest_algorithm": cms.DigestAlgorithm(
                                        {
                                            "algorithm": algorithm.digest,
                                            "parameters": None,
                                        }
                                    ),
                                    "signature_algorithm": cms.SignedDigestAlgorithm(
                                        {
                                            "algorithm": algorithm.signature,
                                            "parameters": None,
                                        }
                                    ),
                                }
                            )
                        ],
                    }
                ),
                cms.CMSAttribute(
                    {
                        "type": "message_digest",
                        "values": [digest],
                    }
                ),
            ]
        )

        signed_attrs = algorithm.sign(attrs.dump())

        signer_info = cms.SignerInfo(
            {
                "version": "v1",
                "digest_algorithm": algos.DigestAlgorithm(
                    {"algorithm": algorithm.digest}
                ),
                "signature_algorithm": algos.SignedDigestAlgorithm(
                    {"algorithm": algorithm.signature}
                ),
                "signature": signed_attrs,
                "sid": cms.SignerIdentifier(
                    {
                        "issuer_and_serial_number": cms.IssuerAndSerialNumber(
                            {
                                "issuer": cert.issuer,
                                "serial_number": cert.serial_number,
                            }
                        )
                    }
                ),
                "signed_attrs": attrs,
            }
        )

        signed_data = {
            "version": "v1",
            "digest_algorithms": [
                algos.DigestAlgorithm({"algorithm": algorithm.digest})
            ],
            "encap_content_info": encap_content_info,
            "certificates": [cert],
            "signer_infos": [signer_info],
        }

        return cms.ContentInfo(
            {
                "content_type": "signed_data",
                "content": cms.SignedData(signed_data),
            }
        )

    def _perform_signature(self, sig_field_value: DictionaryObject) -> bool:
        """Create the signature content and fill the /ByteRange and /Contents properties.

        :param sig_field_value: the value (/V) of the signature field to modify.
        :return: True on success, False if the signature could not be created.
        :rtype: bool
        """
        private_key, certificate = self._load_key_and_certificate()
        if private_key is None or certificate is None:
            return False
        algorithm = self._get_signature_algorithm(private_key)
        if algorithm is None:
            _logger.warning(
                "Cannot sign PDF: unsupported private key type %s "
                "(supported: RSA, EC, Ed25519)",
                type(private_key).__name__,
            )
            return False

        pdf_data = self._get_document_data()

        signature_field_pos = pdf_data.rfind(b"/FT /Sig")
        if signature_field_pos == -1:
            _logger.warning(
                "Cannot sign PDF: no /FT /Sig field in the serialized document"
            )
            return False
        contents_field_pos = pdf_data.find(b"Contents", signature_field_pos)
        if contents_field_pos == -1:
            _logger.warning(
                "Cannot sign PDF: no /Contents entry after the signature field"
            )
            return False

        placeholder_start = contents_field_pos + 9
        placeholder_end = placeholder_start + self._CONTENTS_PLACEHOLDER_BYTES * 2 + 2
        placeholder = b"<" + b"0" * (self._CONTENTS_PLACEHOLDER_BYTES * 2) + b">"
        if pdf_data[placeholder_start:placeholder_end] != placeholder:
            _logger.warning(
                "Cannot sign PDF: /Contents placeholder not found at the "
                "computed offset"
            )
            return False

        placeholder_byte_range = sig_field_value.get("/ByteRange")

        byte_range = [
            0,
            placeholder_start,
            placeholder_end,
            abs(len(pdf_data) - placeholder_end),
        ]

        byte_range = self._correct_byte_range(
            placeholder_byte_range, byte_range, len(pdf_data)
        )

        sig_field_value.update(
            {NameObject("/ByteRange"): self._create_number_array_object(byte_range)}
        )

        pdf_data = self._get_document_data()

        digest = self._compute_digest_from_byte_range(
            pdf_data, byte_range, algorithm.digest
        )

        cms_content_info = self._get_cms_object(digest, certificate, algorithm)

        signature_der = cms_content_info.dump()
        if len(signature_der) > self._CONTENTS_PLACEHOLDER_BYTES:
            raise ValueError(
                f"PDF signature ({len(signature_der)} bytes) exceeds the reserved "
                f"{self._CONTENTS_PLACEHOLDER_BYTES} bytes; the certificate is too large to embed."
            )
        signature_hex = signature_der.hex().ljust(
            self._CONTENTS_PLACEHOLDER_BYTES * 2, "0"
        )

        sig_field_value.update(
            {NameObject("/Contents"): ByteStringObject(bytes.fromhex(signature_hex))}
        )
        return True

    def _get_document_data(self) -> bytes:
        """Retrieve the bytes of the document from the writer."""
        output_stream = io.BytesIO()
        self.writer.write_stream(output_stream)
        return output_stream.getvalue()

    def _correct_byte_range(
        self, old_range: list[int], new_range: list[int], base_pdf_len: int
    ) -> list[int]:
        """Correct the last value of the new byte range.

        The initial byte range (old_range) was computed for a document still containing the
        placeholder values for the /ByteRange and /Contents fields. Updating /ByteRange changes
        the document length, so the range must be recomputed to stay valid.

        :param old_range: the previous byte range.
        :param new_range: the new byte range.
        :param base_pdf_len: the length of the pdf before insertion of the actual byte range.
        :return: the corrected byte range.
        :rtype: list[int]
        """
        current_len = len(str(old_range))
        corrected_len = len(str(new_range))
        diff = corrected_len - current_len

        if diff == 0:
            return new_range

        corrected_range = new_range.copy()
        corrected_range[-1] = abs((base_pdf_len + diff) - new_range[-2])
        return self._correct_byte_range(new_range, corrected_range, base_pdf_len)

    def _compute_digest_from_byte_range(
        self, data: bytes, byte_range: list[int], algorithm: str = "sha256"
    ) -> bytes:
        """Compute the digest of the data selected by a byte range.

        The byte range is an array [offset, length, offset, length, ...] selecting the bytes
        of the document used to compute the hash. E.g. for data = b'example' and
        byte_range = [0, 1, 6, 1], the hash is computed from b'ee'.

        :param data: the data in bytes.
        :param byte_range: the byte range used to compute the digest.
        :param algorithm: the hashlib algorithm name.
        :return: the computed digest.
        :rtype: bytes
        """
        hashed = hashlib.new(algorithm)
        for i in range(0, len(byte_range), 2):
            hashed.update(data[byte_range[i] : byte_range[i] + byte_range[i + 1]])
        return hashed.digest()

    def _create_number_array_object(self, array: list[int]) -> ArrayObject:
        return ArrayObject([NumberObject(item) for item in array])
