import email
import email.policy

import pytest

from addons.mail.tools.mime import extract_payload, postprocess_payload

HEADERS = (
    b"From: <sender@example.com>\r\n"
    b"To: <inbox@example.com>\r\n"
    b"Subject: Test\r\n"
    b"Message-Id: <test@example.com>\r\n"
    b"Date: Wed, 19 Aug 2026 10:00:00 +0000\r\n"
)

ACCENTED = "Café naïve — über".encode()


def parse(raw: bytes):
    return email.message_from_bytes(raw, policy=email.policy.SMTP)


def payload(raw: bytes, **kwargs):
    return postprocess_payload(extract_payload(parse(raw), **kwargs))


def multipart(subtype: bytes, boundary: bytes, *parts: bytes) -> bytes:
    body = b"".join(b"--" + boundary + b"\r\n" + part + b"\r\n" for part in parts)
    return (
        b"Content-Type: multipart/" + subtype + b'; boundary="' + boundary + b'"\r\n'
        b"\r\n" + body + b"--" + boundary + b"--\r\n"
    )


PLAIN = b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
HTML = b"Content-Type: text/html; charset=utf-8\r\n\r\n"


class TestUndeclaredCharset:
    @pytest.mark.parametrize("content_type", [b"text/plain", b"text/html"])
    def test_single_part_without_charset_is_read_as_utf8(self, content_type):
        body = payload(
            HEADERS + b"Content-Type: " + content_type + b"\r\n\r\n" + ACCENTED
        ).body
        assert "Café naïve — über" in body
        assert "�" not in body

    def test_a_declared_charset_is_still_honoured(self):
        raw = (
            HEADERS
            + b"Content-Type: text/plain; charset=iso-8859-1\r\n\r\n"
            + "Café".encode("iso-8859-1")
        )
        assert "Café" in payload(raw).body

    def test_container_and_bare_message_agree(self):
        bare = payload(HEADERS + b"Content-Type: text/plain\r\n\r\n" + ACCENTED).body
        wrapped = payload(
            HEADERS
            + multipart(b"mixed", b"M", b"Content-Type: text/plain\r\n\r\n" + ACCENTED)
        ).body
        assert bare.strip() == wrapped.strip()


class TestAlternative:
    def test_html_wins_over_plain(self):
        result = payload(
            HEADERS
            + multipart(b"alternative", b"A", PLAIN + b"PLAIN", HTML + b"<p>HTML</p>")
        )
        assert "HTML" in result.body
        assert "PLAIN" not in result.body
        assert result.attachments == []

    def test_text_before_an_alternative_is_not_lost(self):
        result = payload(
            HEADERS
            + multipart(
                b"mixed",
                b"M",
                PLAIN + b"INTRO",
                multipart(
                    b"alternative",
                    b"A",
                    PLAIN + b"ALT-PLAIN",
                    HTML + b"<p>ALT-HTML</p>",
                ),
            )
        )
        assert "INTRO" in result.body
        assert "ALT-HTML" in result.body
        assert result.attachments == []

    def test_text_after_an_alternative_is_body_not_attachment(self):
        result = payload(
            HEADERS
            + multipart(
                b"mixed",
                b"M",
                multipart(
                    b"alternative",
                    b"A",
                    PLAIN + b"ALT-PLAIN",
                    HTML + b"<p>ALT-HTML</p>",
                ),
                PLAIN + b"FOOTER",
            )
        )
        assert "FOOTER" in result.body
        assert result.attachments == []

    def test_a_multipart_branch_outranks_the_plain_fallback(self):
        result = payload(
            HEADERS
            + multipart(
                b"alternative",
                b"A",
                PLAIN + b"FALLBACK",
                multipart(
                    b"mixed",
                    b"B",
                    HTML + b"<p>RICH</p>",
                    b'Content-Type: application/pdf; name="doc.pdf"\r\n\r\nPDF',
                ),
            )
        )
        assert "RICH" in result.body
        assert "FALLBACK" not in result.body
        assert [a.fname for a in result.attachments] == ["doc.pdf"]

    def test_an_attachment_in_a_rejected_branch_survives(self):
        result = payload(
            HEADERS
            + multipart(
                b"alternative",
                b"A",
                multipart(
                    b"alternative", b"B", PLAIN + b"PLAIN", HTML + b"<p>HTML</p>"
                ),
                b'Content-Disposition: attachment; filename="bis3.xml"\r\n'
                b'Content-Type: text/xml; name="bis3.xml"\r\n\r\n<Invoice/>',
            )
        )
        assert "HTML" in result.body
        assert [a.fname for a in result.attachments] == ["bis3.xml"]


class TestInlineImages:
    IMG = HTML + b'<p>see <img src="cid:abc123"></p>'

    @pytest.mark.parametrize(
        ("image_headers", "expected_name"),
        [
            (b"Content-Type: image/png\r\nContent-ID: <abc123>\r\n", "attachment"),
            (
                b'Content-Type: image/png; name="logo.png"\r\nContent-ID: <abc123>\r\n',
                "logo.png",
            ),
        ],
    )
    def test_the_cid_is_recorded_with_or_without_a_filename(
        self, image_headers, expected_name
    ):
        result = payload(
            HEADERS + multipart(b"related", b"R", self.IMG, image_headers + b"\r\nPNG")
        )
        assert [a.info.get("cid") for a in result.attachments] == ["abc123"]
        assert [a.fname for a in result.attachments] == [expected_name]
        assert f'data-filename="{expected_name}"' in result.body

    def test_a_related_root_part_is_the_body_not_an_attachment(self):
        result = payload(
            HEADERS
            + multipart(
                b"related",
                b"R",
                b"Content-Type: text/html; charset=utf-8\r\nContent-ID: <root>\r\n\r\n<p>BODY</p>",
            )
        )
        assert "BODY" in result.body
        assert result.attachments == []


class TestAttachedMessage:

    NESTED = (
        b'Content-Type: message/rfc822; name="original_msg.eml"\r\n'
        b'Content-Disposition: attachment; filename="original_msg.eml"\r\n\r\n'
        b"From: <deep@example.com>\r\n"
        b"Subject: Attached\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"INNER BODY"
    )

    def test_an_attached_mail_is_one_file(self):
        result = payload(
            HEADERS + multipart(b"mixed", b"M", PLAIN + b"CARRIER", self.NESTED)
        )
        assert [a.fname for a in result.attachments] == ["original_msg.eml"]

    def test_the_attached_body_is_not_a_second_file(self):
        result = payload(
            HEADERS + multipart(b"mixed", b"M", PLAIN + b"CARRIER", self.NESTED)
        )
        assert "attachment" not in [a.fname for a in result.attachments]

    def test_the_attached_body_does_not_leak_into_the_carrier(self):
        result = payload(
            HEADERS + multipart(b"mixed", b"M", PLAIN + b"CARRIER", self.NESTED)
        )
        assert "CARRIER" in result.body
        assert "INNER BODY" not in result.body

    NESTED_CARRYING_A_FILE = (
        b'Content-Type: message/rfc822; name="original_msg.eml"\r\n'
        b'Content-Disposition: attachment; filename="original_msg.eml"\r\n\r\n'
        b'Content-Type: multipart/mixed; boundary="INNER"\r\n\r\n'
        b"--INNER\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nINNER BODY\r\n"
        b"--INNER\r\n"
        b'Content-Type: application/pdf; name="invoice.pdf"\r\n'
        b'Content-Disposition: attachment; filename="invoice.pdf"\r\n\r\n%PDF-FAKE\r\n'
        b"--INNER--\r\n"
    )

    def test_a_file_inside_the_attached_mail_is_not_lifted_out(self):
        result = payload(
            HEADERS
            + multipart(b"mixed", b"M", PLAIN + b"CARRIER", self.NESTED_CARRYING_A_FILE)
        )
        assert [a.fname for a in result.attachments] == ["original_msg.eml"]
        assert "INNER BODY" not in result.body

    def test_the_nested_file_survives_inside_the_archive(self):
        [attached] = payload(
            HEADERS
            + multipart(b"mixed", b"M", PLAIN + b"CARRIER", self.NESTED_CARRYING_A_FILE)
        ).attachments
        assert b"%PDF-FAKE" in attached.content.as_bytes()

    def test_the_attached_mail_is_kept_whole(self):
        [attached] = payload(
            HEADERS + multipart(b"mixed", b"M", PLAIN + b"CARRIER", self.NESTED)
        ).attachments
        assert b"INNER BODY" in attached.content.as_bytes()


class TestSaveOriginal:
    def test_the_archive_holds_the_delivered_bytes(self):
        raw = HEADERS + b"Content-Type: text/plain; charset=utf-8\r\n\r\n" + ACCENTED
        archive = payload(raw, save_original=True).attachments[0]
        assert archive.fname == "original_email.eml"
        assert isinstance(archive.content, bytes)
        assert ACCENTED in archive.content

    def test_the_archive_survives_an_undeclared_charset(self):
        raw = HEADERS + b"Content-Type: text/plain\r\n\r\n" + ACCENTED
        archive = payload(raw, save_original=True).attachments[0]
        assert ACCENTED in archive.content

    def test_the_archive_is_captured_before_the_headers_are_repaired(self):
        raw = HEADERS + b"Content-Type: text/plain\r\n\r\n" + ACCENTED
        archive = payload(raw, save_original=True).attachments[0]
        assert b"charset" not in archive.content.split(b"\r\n\r\n", 1)[0].lower()


class TestBadContentTypes:
    def test_a_placeholder_content_type_is_kept_as_a_file(self):
        result = payload(
            HEADERS
            + multipart(
                b"mixed",
                b"M",
                PLAIN + b"body",
                b'Content-Type: binary/octet-stream; name="hello.dat"\r\n\r\ndata',
            )
        )
        assert [a.fname for a in result.attachments] == ["hello.dat"]

    def test_an_aliased_pdf_type_is_corrected(self):
        result = payload(
            HEADERS
            + multipart(
                b"mixed",
                b"M",
                PLAIN + b"body",
                b'Content-Type: pdf; name="d.pdf"\r\n\r\ndata',
            )
        )
        assert [a.fname for a in result.attachments] == ["d.pdf"]


class TestBounce:
    def test_a_bounce_stops_at_the_first_body(self):
        result = payload(
            HEADERS
            + multipart(
                b"report",
                b"M",
                PLAIN + b"NOTICE: delivery failed",
                PLAIN + b"ORIGINAL MESSAGE TEXT",
            ),
            is_bounce=True,
        )
        assert "NOTICE" in result.body
        assert "ORIGINAL MESSAGE TEXT" not in result.body


class TestDegenerateMessages:
    def test_an_empty_multipart_yields_an_empty_body(self):
        result = payload(
            HEADERS + b'Content-Type: multipart/mixed; boundary="M"\r\n\r\n'
        )
        assert result.body.strip() == ""
        assert result.attachments == []

    def test_an_empty_alternative_yields_an_empty_body(self):
        result = payload(
            HEADERS + b'Content-Type: multipart/alternative; boundary="A"\r\n\r\n'
        )
        assert result.body.strip() == ""

    def test_a_part_naming_an_unknown_charset_is_not_fatal(self):
        raw = (
            HEADERS
            + b"Content-Type: text/plain; charset=x-not-a-charset\r\n\r\n"
            + ACCENTED
        )
        assert payload(raw).body

    def test_deep_nesting_is_flattened_in_order(self):
        result = payload(
            HEADERS
            + multipart(
                b"mixed",
                b"M",
                multipart(b"mixed", b"N", PLAIN + b"ONE", PLAIN + b"TWO"),
                PLAIN + b"THREE",
            )
        )
        assert (
            result.body.index("ONE")
            < result.body.index("TWO")
            < result.body.index("THREE")
        )
