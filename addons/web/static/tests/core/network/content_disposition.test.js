// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { parse } from "@web/core/network/content_disposition";

describe.current.tags("headless");

describe("the disposition type", () => {
    test("is lower-cased and separated from its parameters", () => {
        expect(parse("inline").type).toBe("inline");
        expect(parse("INLINE").type).toBe("inline");
        expect(parse('INLINE; FileName="X.PDF"').type).toBe("inline");
        expect(parse('form-data; name="field"; filename="f.txt"').type).toBe(
            "form-data",
        );
    });

    test("a bare type carries no parameters", () => {
        expect(parse("inline").parameters).toEqual({});
    });
});

describe("filename", () => {
    test("quoted, unquoted, and unspaced forms all read the same", () => {
        for (const header of [
            'attachment; filename="report.pdf"',
            "attachment; filename=report.pdf",
            'attachment;filename="report.pdf"',
        ]) {
            expect(parse(header).parameters.filename).toBe("report.pdf", {
                message: header,
            });
        }
    });

    test("parameter names are case-insensitive", () => {
        expect(parse('inline; FileName="X.PDF"').parameters.filename).toBe("X.PDF");
    });

    test("a quoted value may contain the parameter separator", () => {
        expect(parse('attachment; filename="a;b.pdf"').parameters.filename).toBe(
            "a;b.pdf",
        );
        expect(
            parse('attachment; filename="Invoice INV/2024/0001.pdf"').parameters
                .filename,
        ).toBe("Invoice INV/2024/0001.pdf");
    });

    test("backslash escapes inside a quoted value are unescaped", () => {
        expect(
            parse('attachment; filename="quote \\"q\\".pdf"').parameters.filename,
        ).toBe('quote "q".pdf');
    });
});

describe("RFC 5987 extended values", () => {
    test("utf-8 is percent-decoded", () => {
        expect(
            parse("attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf").parameters
                .filename,
        ).toBe("résumé.pdf");
    });

    test("iso-8859-1 is decoded byte-wise", () => {
        expect(
            parse("attachment; filename*=iso-8859-1''caf%E9.txt").parameters.filename,
        ).toBe("café.txt");
    });

    test("filename* wins over filename whichever comes first", () => {
        const extendedFirst =
            "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf; filename=\"resume.pdf\"";
        const plainFirst =
            "attachment; filename=\"resume.pdf\"; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf";
        expect(parse(extendedFirst).parameters.filename).toBe("résumé.pdf");
        expect(parse(plainFirst).parameters.filename).toBe("résumé.pdf");
    });
});

describe("malformed headers are rejected, not guessed at", () => {
    /**
     * @param {string} header
     * @param {string} message
     */
    function expectRejection(header, message) {
        let error = null;
        try {
            parse(header);
        } catch (e) {
            error = e;
        }
        expect(error).not.toBe(null, { message: `${header} must be rejected` });
        expect(error.message).toBe(message);
    }

    test("each malformed shape reports why", () => {
        expectRejection("", "argument string is required");
        expectRejection("atta chment", "invalid type format");
        expectRejection("attachment; ; filename=x", "invalid parameter format");
        expectRejection(
            'attachment; filename="a"; filename="b"',
            "invalid duplicate parameter",
        );
        expectRejection(
            "attachment; filename*=shift_jis''a",
            "unsupported charset in extended field",
        );
        expectRejection(
            "attachment; filename*=UTF-8''%E0%A4%A",
            "invalid extended field value",
        );
    });
});
