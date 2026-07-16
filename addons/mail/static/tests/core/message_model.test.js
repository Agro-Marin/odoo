import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { markup } from "@odoo/owl";
import { getService, serverState } from "@web/../tests/web_test_helpers";
import { deserializeDateTime, serializeDateTime } from "@web/core/l10n/dates";

describe.current.tags("desktop");
defineMailModels();

test("Message model properties", async () => {
    await start();
    const store = getService("mail.store");
    store.Store.insert({
        self_partner: { id: serverState.partnerId },
    });
    store.Thread.insert({
        id: serverState.partnerId,
        model: "res.partner",
        name: "general",
    });
    store["ir.attachment"].insert({
        id: 750,
        mimetype: "text/plain",
        name: "test.txt",
    });
    const message = store["mail.message"].insert({
        attachment_ids: 750,
        author_id: { id: 5, name: "Demo" },
        body: markup`<p>Test</p>`,
        date: deserializeDateTime("2019-05-05 10:00:00"),
        id: 4000,
        starred: true,
        model: "res.partner",
        thread: { id: serverState.partnerId, model: "res.partner" },
        res_id: serverState.partnerId,
    });
    expect(message.body?.toString()).toBe("<p>Test</p>");
    expect(serializeDateTime(message.date)).toBe("2019-05-05 10:00:00");
    expect(message.id).toBe(4000);
    expect(message.attachment_ids[0].name).toBe("test.txt");
    expect(message.thread.id).toBe(serverState.partnerId);
    expect(message.thread.name).toBe("general");
    expect(message.author_id.id).toBe(5);
    expect(message.author_id.name).toBe("Demo");
});

test("extra_body_attachment_ids excludes attachments inlined in the body", async () => {
    await start();
    const store = getService("mail.store");
    store["ir.attachment"].insert([
        { id: 750, mimetype: "image/png", name: "inlined.png" },
        { id: 751, mimetype: "application/pdf", name: "doc.pdf" },
    ]);
    const message = store["mail.message"].insert({
        id: 4100,
        attachment_ids: [750, 751],
        body: markup`<p>hi</p><img data-attachment-id="750">`,
        model: "res.partner",
        res_id: serverState.partnerId,
    });
    // 750 is rendered inline in the body, so only 751 is an "extra" attachment.
    expect(message.extra_body_attachment_ids.length).toBe(1);
    expect(message.extra_body_attachment_ids[0].id).toBe(751);
});
