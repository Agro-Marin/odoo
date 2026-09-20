// @ts-check
import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { markup } from "@odoo/owl";
import { getService, serverState } from "@web/../tests/web_test_helpers";
import { deserializeDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";

const { DateTime } = luxon;

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
    expect(message.extra_body_attachment_ids.length).toBe(1);
    expect(message.extra_body_attachment_ids[0].id).toBe(751);
});

test("bubbleColor: mention wins, a note has none, otherwise self is green and others blue", async () => {
    await start();
    const store = getService("mail.store");
    store.Store.insert({
        self_partner: { id: serverState.partnerId },
        mt_note: { id: 2 },
    });
    const channel = store.Thread.insert({
        id: 11,
        model: "discuss.channel",
        name: "general",
    });
    const other = { id: 5, name: "Demo" };
    const self = { id: serverState.partnerId };
    const insert = (id, vals) =>
        store["mail.message"].insert({
            id,
            model: "discuss.channel",
            res_id: 11,
            thread: channel,
            message_type: "comment",
            ...vals,
        });
    expect(insert(1, { author_id: other }).bubbleColor).toBe("blue");
    expect(insert(2, { author_id: self }).bubbleColor).toBe("green");
    expect(insert(3, { author_id: other, subtype_id: { id: 2 } }).bubbleColor).toBe(
        undefined,
    );
    expect(insert(4, { author_id: other, partner_ids: [self] }).bubbleColor).toBe(
        "orange",
    );
    expect(
        insert(5, { author_id: other, partner_ids: [self], subtype_id: { id: 2 } })
            .bubbleColor,
    ).toBe("orange");
    expect(
        insert(6, { author_id: other, message_type: "notification" }).bubbleColor,
    ).toBe(undefined);
});

test("dateDay reads Today for a message of the current day", async () => {
    await start();
    const store = getService("mail.store");
    const today = store["mail.message"].insert({ id: 1, date: DateTime.now() });
    expect(today.dateDay).toBe("Today");
    const earlier = store["mail.message"].insert({
        id: 2,
        date: deserializeDateTime("2019-05-05 10:00:00"),
    });
    expect(earlier.dateDay).toBe(
        deserializeDateTime("2019-05-05 10:00:00").toLocaleString(DateTime.DATE_MED),
    );
});
