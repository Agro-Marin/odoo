// @ts-check
import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { getService } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("Attachment model properties", async () => {
    await start();
    const attachment = getService("mail.store")["ir.attachment"].insert({
        id: 750,
        mimetype: "text/plain",
        name: "test.txt",
    });
    expect(attachment.isText).toBe(true);
    expect(attachment.isViewable).toBe(true);
    expect(attachment.mimetype).toBe("text/plain");
    expect(attachment.name).toBe("test.txt");
    expect(attachment.extension).toBe("txt");
});

test("the extension is derived from the name only while the server gives none", async () => {
    await start();
    const store = getService("mail.store");
    const derived = store["ir.attachment"].insert({
        id: 751,
        name: "report.final.PDF",
    });
    expect(derived.extension).toBe("PDF");
    derived.name = "report.docx";
    expect(derived.extension).toBe("PDF");
    const given = store["ir.attachment"].insert({
        id: 752,
        name: "x.txt",
        extension: "text",
    });
    expect(given.extension).toBe("text");
    const nameless = store["ir.attachment"].insert({ id: 753, name: false });
    expect(nameless.extension).toBe(undefined);
    nameless.name = "late.png";
    expect(nameless.extension).toBe("png");
});
