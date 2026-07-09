import base64
import io
import re
import unicodedata
from datetime import datetime
from hashlib import md5
from logging import getLogger
from typing import Any, TYPE_CHECKING
from zlib import compress, decompress, decompressobj

from PIL import Image, PdfImagePlugin

from odoo import modules
from odoo.libs.text.arabic_reshaper import reshape
from odoo.libs.parse_version import parse_version
from odoo.tools.misc import file_open, SENTINEL

from . import _pypdf as pypdf

if TYPE_CHECKING:
    from collections.abc import Generator

PdfReaderBase, PdfWriter, filters, generic, errors, create_string_object = (
    pypdf.PdfReader,
    pypdf.PdfWriter,
    pypdf.filters,
    pypdf.generic,
    pypdf.errors,
    pypdf.create_string_object,
)
# because they got re-exported
(
    ArrayObject,
    BooleanObject,
    ByteStringObject,
    DecodedStreamObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
) = (
    generic.ArrayObject,
    generic.BooleanObject,
    generic.ByteStringObject,
    generic.DecodedStreamObject,
    generic.DictionaryObject,
    generic.IndirectObject,
    generic.NameObject,
    generic.NumberObject,
)

# compatibility aliases
PdfReadError = errors.PdfReadError  # moved in 2.0
PdfStreamError = errors.PdfStreamError  # moved in 2.0
try:
    DependencyError = errors.DependencyError
except AttributeError:
    DependencyError = NotImplementedError

# ----------------------------------------------------------
# PyPDF2 hack
# ensure that zlib does not throw error -5 when decompressing
# because some pdf won't fit into allocated memory
# https://docs.python.org/3/library/zlib.html#zlib.decompressobj
# ----------------------------------------------------------
pypdf.filters.decompress = lambda data: decompressobj().decompress(data)


# monkey patch to discard unused arguments as the old arguments were not discarded in the transitional class
# This keep the old default value of the `strict` argument
# https://github.com/py-pdf/pypdf/blob/1.26.0/PyPDF2/pdf.py#L1061
# https://pypdf2.readthedocs.io/en/2.0.0/_modules/PyPDF2/_reader.html#PdfReader
class PdfReader(PdfReaderBase):
    def __init__(
        self, stream: io.BytesIO | str, strict: bool = True, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(stream, strict)


PdfFileReader = PdfReader

_logger = getLogger(__name__)
DEFAULT_PDF_DATETIME_FORMAT = "D:%Y%m%d%H%M%S+00'00'"
REGEX_SUBTYPE_UNFORMATED = re.compile(r"^\w+/[\w-]+$")
REGEX_SUBTYPE_FORMATED = re.compile(r"^/\w+#2F[\w-]+$")


# Disable linter warning: this import is needed to make sure a PDF stream can be saved in Image.
PdfImagePlugin.__name__  # noqa: B018  # touch the import so PIL registers the PDF plugin (see comment above)


# make sure values are unwrapped by calling the specialized __getitem__
def _unwrapping_get(self: Any, key: Any, default: Any = None) -> Any:
    """Get a value from a DictionaryObject, unwrapping indirect references."""
    try:
        return self[key]
    except KeyError:
        return default


DictionaryObject.get = _unwrapping_get


if hasattr(NameObject, "renumber_table"):
    # Make sure all the correct delimiters are included
    # We will make this change only if pypdf has the renumber_table attribute
    # https://github.com/py-pdf/pypdf/commit/8c542f331828c5839fda48442d89b8ac5d3984ac
    NameObject.renumber_table.update(
        {
            **{chr(i): f"#{i:02X}".encode() for i in b"#()<>[]{}/%"},
            **{chr(i): f"#{i:02X}".encode() for i in range(33)},
        }
    )


class BrandedFileWriter(PdfWriter):
    def write_stream(self, *args: Any, **kwargs: Any) -> None:
        """Write stream with Odoo metadata branding."""
        self.add_metadata(
            {
                "/Creator": "Odoo",
                "/Producer": "Odoo",
            }
        )
        super().write_stream(*args, **kwargs)


PdfFileWriter = BrandedFileWriter


def merge_pdf(pdf_data: list[bytes]) -> bytes:
    """Merge a collection of PDF documents in one.

    Attachments are not merged.

    :param pdf_data: a list of PDF datastrings
    :return: a unique merged PDF datastring
    """
    writer = PdfFileWriter()
    for document in pdf_data:
        reader = PdfFileReader(io.BytesIO(document), strict=False)
        for page in range(len(reader.pages)):
            writer.add_page(reader.pages[page])

    with io.BytesIO() as _buffer:
        writer.write(_buffer)
        return _buffer.getvalue()


def fill_form_fields_pdf(writer: PdfWriter, form_fields: dict[str, Any]) -> None:
    """Fill in the form fields of a PDF.

    :param writer: a PdfFileWriter object
    :param form_fields: a dictionary of form fields to update in the PDF
    """

    # This solves a known problem where with some pdf software, form fields aren't
    # correctly filled until the user clicks on them. See: https://github.com/py-pdf/pypdf/issues/355
    writer.set_need_appearances_writer()

    for page_id in range(len(writer.pages)):
        page = writer.pages[page_id]
        writer.update_page_form_field_values(page, form_fields)


def rotate_pdf(pdf: bytes) -> bytes:
    """Rotate clockwise PDF (90°) into a new PDF.

    Attachments are not copied.

    :param pdf: a PDF to rotate
    :return: a PDF rotated
    """
    writer = PdfFileWriter()
    reader = PdfFileReader(io.BytesIO(pdf), strict=False)
    for page in range(len(reader.pages)):
        page = reader.pages[page]
        page.rotate(90)
        writer.add_page(page)
    with io.BytesIO() as _buffer:
        writer.write(_buffer)
        return _buffer.getvalue()


def to_pdf_stream(attachment) -> io.BytesIO | None:
    """Get the byte stream of the attachment as a PDF."""
    if not attachment.raw:
        _logger.warning("%s has no raw data.", attachment)
        return None

    if attachment_raw := attachment._get_pdf_raw():
        return io.BytesIO(attachment_raw)
    stream = io.BytesIO(attachment.raw)
    if attachment.mimetype.startswith("image"):
        output_stream = io.BytesIO()
        Image.open(stream).convert("RGB").save(output_stream, format="pdf")
        return output_stream
    _logger.warning(
        "mimetype (%s) not recognized for %s", attachment.mimetype, attachment
    )
    return None


def extract_page(attachment, num_page=0) -> io.BytesIO | None:
    """Extract a specific page from an attachment PDF."""
    pdf_stream = to_pdf_stream(attachment)
    if not pdf_stream:
        return None
    pdf = PdfFileReader(pdf_stream)
    page = pdf.pages[num_page]
    pdf_writer = PdfFileWriter()
    pdf_writer.add_page(page)
    stream = io.BytesIO()
    pdf_writer.write(stream)
    return stream


def add_banner(
    pdf_stream: io.BytesIO,
    text: str | None = None,
    logo: bool = False,
    thickness: float | object = SENTINEL,
) -> io.BytesIO:
    """Add a banner on a PDF in the upper right corner, with Odoo's logo (optionally).

    :param pdf_stream: The PDF stream where the banner will be applied.
    :param text: The text to be displayed.
    :param logo: Whether to display Odoo's logo in the banner.
    :param thickness: The thickness of the banner (default: 2cm).
    :return: The modified PDF stream.
    """
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    if thickness is SENTINEL:
        from reportlab.lib.units import cm

        thickness = 2 * cm

    old_pdf = PdfFileReader(pdf_stream, strict=False)
    packet = io.BytesIO()
    can = canvas.Canvas(packet)
    with file_open("base/static/img/main_partner-image.png", mode="rb") as f:
        odoo_logo_file = io.BytesIO(f.read())
    odoo_logo = Image.open(odoo_logo_file)
    odoo_color = colors.Color(113 / 255, 75 / 255, 103 / 255, 0.8)

    for p in range(len(old_pdf.pages)):
        page = old_pdf.pages[p]
        width = float(abs(page.mediabox.width))
        height = float(abs(page.mediabox.height))

        can.setPageSize((width, height))
        can.translate(width, height)
        can.rotate(-45)

        # Draw banner
        path = can.beginPath()
        path.moveTo(-width, -thickness)
        path.lineTo(-width, -2 * thickness)
        path.lineTo(width, -2 * thickness)
        path.lineTo(width, -thickness)
        can.setFillColor(odoo_color)
        can.drawPath(path, fill=1, stroke=False)

        # Insert text (and logo) inside the banner
        can.setFontSize(10)
        can.setFillColor(colors.white)
        can.drawRightString(0.75 * thickness, -1.45 * thickness, text)
        logo and can.drawImage(
            ImageReader(odoo_logo),
            0.25 * thickness,
            -2.05 * thickness,
            40,
            40,
            mask="auto",
            preserveAspectRatio=True,
        )

        can.showPage()

    can.save()

    # Merge the old pages with the watermark
    watermark_pdf = PdfFileReader(packet)
    new_pdf = PdfFileWriter()
    for p in range(len(old_pdf.pages)):
        # Add the source page to the writer first, then mutate the writer's
        # writable copy. Mutating a reader page (merge_page/annotation removal)
        # triggers pypdf's replace_contents deprecation and can corrupt object
        # references, causing NullObject errors.
        new_pdf.add_page(old_pdf.pages[p])
        new_page = new_pdf.pages[-1]
        # Remove annotations (if any), to prevent errors in pypdf
        if "/Annots" in new_page:
            del new_page["/Annots"]
        new_page.merge_page(watermark_pdf.pages[p])
        # compress the merged page to bound peak memory and output size —
        # pypdf keeps content streams uncompressed otherwise
        new_page.compress_content_streams()

    # Write the new pdf into a new output stream
    output = io.BytesIO()
    new_pdf.write(output)

    return output


def reshape_text(text: str) -> str:
    """Reshape and reverse text when it is entirely right-to-left (e.g. Arabic).

    Direction is detected from Unicode bidirectional classes: the text is treated as
    right-to-left when its first character is 'R' or 'AL' and no other character is 'L'.
    See https://www.unicode.org/reports/tr9/#Bidirectional_Character_Types.
    """
    if not text:
        return ""
    maybe_rtl_letter = text.lstrip()[:1] or " "
    maybe_ltr_text = text[1:]
    first_letter_is_rtl = unicodedata.bidirectional(maybe_rtl_letter) in (
        "AL",
        "R",
    )
    no_letter_is_ltr = not any(
        unicodedata.bidirectional(letter) == "L" for letter in maybe_ltr_text
    )
    if first_letter_is_rtl and no_letter_is_ltr:
        text = reshape(text)
        text = text[::-1]

    return text


class OdooPdfFileReader(PdfFileReader):
    """Override of PdfFileReader to add management of multiple embedded files.

    :raises NotImplementedError: if document is encrypted with an unsupported method.
    """

    def get_attachments(self) -> Generator[tuple[str, bytes]]:
        if self.is_encrypted:
            # If the PDF is owner-encrypted, try to unwrap it by giving it an empty user password.
            self.decrypt("")

        def _traverse_nodes(obj):
            # /EmbeddedFiles may organise files as a flat /Names array or as a
            # /Kids tree of child nodes each carrying their own /Names
            for p in obj.get("/Names", [])[1::2]:
                attachment = p.get_object()
                try:
                    yield (
                        attachment["/F"],
                        attachment["/EF"]["/F"].get_object().get_data(),
                    )
                except (KeyError, AttributeError):
                    continue
            for kid in obj.get("/Kids", []):
                if id(kid) not in visited_nodes:
                    visited_nodes.add(id(kid))
                    yield from _traverse_nodes(kid.get_object())

        try:
            embedded_files = (
                self.trailer["/Root"].get("/Names", {}).get("/EmbeddedFiles", {})
            )
            if not embedded_files:
                return []
            visited_nodes = set()
            yield from _traverse_nodes(embedded_files)
        except Exception:
            # malformed pdf (i.e. invalid xref page)
            return []


class OdooPdfFileWriter(PdfFileWriter):
    """Extended PdfFileWriter with Odoo-specific attachment and PDF/A support."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialise the writer with Odoo-specific attributes."""
        super().__init__(*args, **kwargs)
        self._reader: PdfReader | None = None
        self.is_pdfa: bool = False

    def format_subtype(self, subtype: str | None) -> str | None:
        """Apply the correct format to the subtype.

        It should take the form of "/xxx#2Fxxx". E.g. for "text/xml": "/text#2Fxml".

        :param subtype: The mime-type of the attachement.
        """
        if not subtype:
            return subtype

        adapted_subtype = subtype
        if REGEX_SUBTYPE_UNFORMATED.match(subtype):
            # pypdf does the formatting when creating a NameObject
            return "/" + subtype

        if not REGEX_SUBTYPE_FORMATED.match(adapted_subtype):
            # The subtype still does not match the correct format, so we will not add it to the document
            _logger.warning(
                "Attempt to add an attachment with the incorrect subtype '%s'. The subtype will be ignored.",
                subtype,
            )
            adapted_subtype = ""
        return adapted_subtype

    def add_attachment(
        self,
        name: str,
        data: bytes,
        subtype: str | None = None,
        afrelationship: str = "/Data",
    ) -> None:
        """Add an attachment to the PDF, respecting PDF/A rules.

        :param name: The name of the attachement
        :param data: The data of the attachement
        :param subtype: The mime-type of the attachement. Required by PDF/A.
        :param afrelationship: The relationship between the embedded file and
            the PDF content. Required by PDF/A.
        """
        # Valid AFRelationship values per PDF 2.0 spec (ISO 32000-2, section 7.11.3)
        valid_afrelationships = {
            "/Source",
            "/Data",
            "/Alternative",
            "/Supplement",
            "/Unspecified",
            "/EncryptedPayload",
            "/FormData",
            "/Schema",
        }
        if afrelationship not in valid_afrelationships:
            _logger.warning(
                "Invalid AFRelationship value '%s', falling back to '/Data'. "
                "Valid values are: %s",
                afrelationship,
                ", ".join(sorted(valid_afrelationships)),
            )
            afrelationship = "/Data"

        adapted_subtype = self.format_subtype(subtype)

        attachment = self._create_attachment_object(
            {
                "filename": name,
                "content": data,
                "subtype": adapted_subtype,
                "afrelationship": afrelationship,
            }
        )
        if self._root_object.get("/Names") and self._root_object["/Names"].get(
            "/EmbeddedFiles"
        ):
            names_array = self._root_object["/Names"]["/EmbeddedFiles"]["/Names"]
            names_array.extend([attachment.get_object()["/F"], attachment])
        else:
            names_array = ArrayObject()
            names_array.extend([attachment.get_object()["/F"], attachment])

            embedded_files_names_dictionary = DictionaryObject()
            embedded_files_names_dictionary.update({NameObject("/Names"): names_array})
            embedded_files_dictionary = DictionaryObject()
            embedded_files_dictionary.update(
                {NameObject("/EmbeddedFiles"): embedded_files_names_dictionary}
            )
            self._root_object.update({NameObject("/Names"): embedded_files_dictionary})

        if self._root_object.get("/AF"):
            attachment_array = self._root_object["/AF"]
            attachment_array.extend([attachment])
        else:
            # Create a new object containing an array referencing embedded file
            # And reference this array in the root catalogue
            attachment_array = self._add_object(ArrayObject([attachment]))
            self._root_object.update({NameObject("/AF"): attachment_array})

    def embed_odoo_attachment(
        self,
        attachment: Any,
        subtype: str | None = None,
        afrelationship: str = "/Data",
    ) -> None:
        """Embed an Odoo ir.attachment record into the PDF."""
        assert attachment, "embed_odoo_attachment cannot be called without attachment."
        self.add_attachment(
            attachment.name,
            attachment.raw,
            subtype=subtype or attachment.mimetype,
            afrelationship=afrelationship,
        )

    def clone_reader_document_root(self, reader: PdfReader) -> None:
        """Clone the document root from a reader, preserving PDF/A headers."""
        super().clone_reader_document_root(reader)
        self._reader = reader
        # Try to read the header coming in, and reuse it in our new PDF
        # This is done in order to allows modifying PDF/A files after creating them (as PyPDF does not read it)
        stream = reader.stream
        stream.seek(0)
        header = stream.readlines(9)
        # Should always be true, the first line of a pdf should have 9 bytes (%PDF-1.x plus a newline)
        if len(header) == 1:
            # If we found a header, set it back to the new pdf
            self._header = header[0]
            # Also check the second line. If it is PDF/A, it should be a line starting by % following by four bytes + \n
            second_line = stream.readlines(1)[0]
            if second_line.decode("latin-1")[0] == "%" and len(second_line) == 6:
                self.is_pdfa = True
        # clone_reader_document_root clones reader._ID since 3.2 (py-pdf/pypdf#1520)
        if not hasattr(self, "_ID"):
            # Look if we have an ID in the incoming stream and use it.
            self._set_id(reader.trailer.get("/ID", None))

    def _set_id(self, pdf_id: Any) -> None:
        """Set the PDF document ID in the trailer."""
        if not pdf_id:
            return

        # property in pypdf
        if hasattr(type(self), "_ID"):
            self.trailers["/ID"] = pdf_id
        else:
            self._ID = pdf_id

    def convert_to_pdfa(self) -> None:
        """Transform the opened PDF file into a PDF/A compliant file."""
        # Set the PDF version to 1.7 (as PDF/A-3 is based on version 1.7) and make it PDF/A compliant.
        # See https://github.com/veraPDF/veraPDF-validation-profiles/wiki/PDFA-Parts-2-and-3-rules#rule-612-1
        self._header = b"%PDF-1.7"

        # pypdf automatically adds the binary comment after the header (%âãÏÓ)

        # Add a document ID to the trailer. This is only needed when using encryption with regular PDF, but is required
        # when using PDF/A
        pdf_id = ByteStringObject(md5(self._reader.stream.getvalue()).digest())
        # The first string is based on the content at the time of creating the file, while the second is based on the
        # content of the file when it was last updated. When creating a PDF, both are set to the same value.
        self._set_id(ArrayObject((pdf_id, pdf_id)))

        with file_open("tools/data/files/sRGB2014.icc", mode="rb") as icc_profile:
            icc_profile_file_data = compress(icc_profile.read())

        icc_profile_stream_obj = DecodedStreamObject()
        icc_profile_stream_obj.set_data(icc_profile_file_data)
        icc_profile_stream_obj.update(
            {
                NameObject("/Filter"): NameObject("/FlateDecode"),
                NameObject("/N"): NumberObject(3),
                NameObject("/Length"): NameObject(str(len(icc_profile_file_data))),
            }
        )

        icc_profile_obj = self._add_object(icc_profile_stream_obj)

        output_intent_dict_obj = DictionaryObject()
        output_intent_dict_obj.update(
            {
                NameObject("/S"): NameObject("/GTS_PDFA1"),
                NameObject("/OutputConditionIdentifier"): create_string_object("sRGB"),
                NameObject("/DestOutputProfile"): icc_profile_obj,
                NameObject("/Type"): NameObject("/OutputIntent"),
            }
        )

        output_intent_obj = self._add_object(output_intent_dict_obj)
        self._root_object.update(
            {
                NameObject("/OutputIntents"): ArrayObject([output_intent_obj]),
            }
        )

        pages = self._root_object["/Pages"]["/Kids"]

        # PDF/A needs the glyphs width array embedded in the pdf to be consistent with the ones from the font file.
        # But it seems like it is not the case when exporting from wkhtmltopdf.
        try:
            import fontTools.ttLib
        except ImportError:
            _logger.warning(
                "The fonttools package is not installed. Generated PDF may not be PDF/A compliant."
            )
        else:
            fonts = {}
            # First browse through all the pages of the pdf file, to get a reference to all the fonts used in the PDF.
            for page in pages:
                for font in page.get_object()["/Resources"]["/Font"].values():
                    for descendant in font.get_object()["/DescendantFonts"]:
                        fonts[descendant.idnum] = descendant.get_object()

            # Then for each font, rewrite the width array with the information taken directly from the font file.
            # The new width are calculated such as width = round(1000 * font_glyph_width / font_units_per_em)
            # See: http://martin.hoppenheit.info/blog/2018/pdfa-validation-and-inconsistent-glyph-width-information/
            for font in fonts.values():
                font_file = font["/FontDescriptor"]["/FontFile2"]
                stream = io.BytesIO(decompress(font_file._data))
                ttfont = fontTools.ttLib.TTFont(stream)
                font_upm = ttfont["head"].unitsPerEm
                if parse_version(fontTools.__version__) < parse_version("4.37.2"):
                    glyphs = ttfont.getGlyphSet()._hmtx.metrics
                else:
                    glyphs = ttfont.getGlyphSet().hMetrics
                glyph_widths = []
                for key, values in glyphs.items():
                    if key[:5] == "glyph":
                        glyph_widths.append(
                            NumberObject(round(1000.0 * values[0] / font_upm))
                        )

                font[NameObject("/W")] = ArrayObject(
                    [NumberObject(1), ArrayObject(glyph_widths)]
                )
                stream.close()

        outlines = self._root_object["/Outlines"].get_object()
        outlines[NameObject("/Count")] = NumberObject(1)

        # [6.7.2.2-1] include a MarkInfo dictionary containing "Marked" with true value
        mark_info = DictionaryObject({NameObject("/Marked"): BooleanObject(True)})
        self._root_object[NameObject("/MarkInfo")] = mark_info

        # [6.7.3.3-1] include minimal document structure in the catalog
        struct_tree_root = DictionaryObject(
            {NameObject("/Type"): NameObject("/StructTreeRoot")}
        )
        self._root_object[NameObject("/StructTreeRoot")] = struct_tree_root

        # Set odoo as producer
        self.add_metadata(
            {
                "/Creator": "Odoo",
                "/Producer": "Odoo",
            }
        )
        self.is_pdfa = True

    def add_file_metadata(self, metadata_content: bytes) -> None:
        """Set the XMP metadata of the PDF, wrapping with necessary XMP header/footer.

        Required for PDF/A compliance. Omitting them results in validation errors.

        :param metadata_content: bytes of the metadata to add to the pdf.
        """
        # See https://wwwimages2.adobe.com/content/dam/acom/en/devnet/xmp/pdfs/XMP%20SDK%20Release%20cc-2016-08/XMPSpecificationPart1.pdf
        # Page 10/11
        header = b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        footer = b'<?xpacket end="w"?>'
        metadata = b"%s%s%s" % (header, metadata_content, footer)
        file_entry = DecodedStreamObject()
        file_entry.set_data(metadata)
        file_entry.update(
            {
                NameObject("/Type"): NameObject("/Metadata"),
                NameObject("/Subtype"): NameObject("/XML"),
                NameObject("/Length"): NameObject(str(len(metadata))),
            }
        )

        # Add the new metadata to the pdf, then redirect the reference to refer to this new object.
        metadata_object = self._add_object(file_entry)
        self._root_object.update({NameObject("/Metadata"): metadata_object})

    def _create_attachment_object(self, attachment: dict[str, Any]) -> Any:
        """Create a pypdf generic object representing an embedded file.

        :param attachment: A dictionary containing:
            * filename: The name of the file to embed (required)
            * content:  The bytes of the file to embed (required)
            * subtype: The mime-type of the file to embed (optional)
            * afrelationship: The PDF/A AFRelationship of the file (optional, defaults to /Data)
        :return: a reference to the created filespec object.
        """
        file_entry = DecodedStreamObject()
        file_entry.set_data(attachment["content"])
        file_entry.update(
            {
                NameObject("/Type"): NameObject("/EmbeddedFile"),
                NameObject("/Params"): DictionaryObject(
                    {
                        NameObject("/CheckSum"): create_string_object(
                            md5(attachment["content"]).hexdigest()
                        ),
                        NameObject("/ModDate"): create_string_object(
                            datetime.now().strftime(DEFAULT_PDF_DATETIME_FORMAT)
                        ),
                        NameObject("/Size"): NumberObject(len(attachment["content"])),
                    }
                ),
            }
        )
        if attachment.get("subtype"):
            file_entry.update(
                {
                    NameObject("/Subtype"): NameObject(attachment["subtype"]),
                }
            )
        file_entry_object = self._add_object(file_entry)
        filename_object = create_string_object(attachment["filename"])
        filespec_object = DictionaryObject(
            {
                NameObject("/AFRelationship"): NameObject(
                    attachment.get("afrelationship", "/Data")
                ),
                NameObject("/Type"): NameObject("/Filespec"),
                NameObject("/F"): filename_object,
                NameObject("/EF"): DictionaryObject(
                    {
                        NameObject("/F"): file_entry_object,
                        NameObject("/UF"): file_entry_object,
                    }
                ),
                NameObject("/UF"): filename_object,
            }
        )
        if attachment.get("description"):
            filespec_object.update(
                {NameObject("/Desc"): create_string_object(attachment["description"])}
            )
        return self._add_object(filespec_object)
