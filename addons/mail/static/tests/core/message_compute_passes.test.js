import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { getService, serverState } from "@web/../tests/web_test_helpers";

/**
 * Computed fields are evaluated in declaration order, and the flush repeats
 * until it converges. A compute that reads another *computed* field declared
 * after it therefore runs twice per record: once against that field's default,
 * once after it settles. It is invisible and costs a full extra evaluation of
 * the dependent field on every record.
 *
 * `mail.message` is the model where that matters most — a thread load inserts
 * dozens at once — so this pins the ordering there: no compute may run more
 * than once while a message is being inserted.
 */
describe.current.tags("desktop");
defineMailModels();

test("inserting a message evaluates each computed field once", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "general" });
    await start();
    const store = getService("mail.store");
    store.Thread.insert({ model: "discuss.channel", id: channelId });

    const Model = store.Models["mail.message"];
    const originals = new Map(Model._.fieldsCompute);
    const runs = new Map();
    for (const [fieldName, fn] of originals) {
        Model._.fieldsCompute.set(fieldName, function () {
            runs.set(fieldName, (runs.get(fieldName) ?? 0) + 1);
            return fn.call(this);
        });
    }
    try {
        store.insert({
            "mail.message": [
                {
                    id: 1,
                    body: "<p>hello</p>",
                    author_id: serverState.partnerId,
                    model: "discuss.channel",
                    res_id: channelId,
                    thread: { id: channelId, model: "discuss.channel" },
                    message_type: "comment",
                    date: "2024-01-01 10:00:00",
                },
            ],
        });
    } finally {
        for (const [fieldName, fn] of originals) {
            Model._.fieldsCompute.set(fieldName, fn);
        }
    }
    const repeated = [...runs.entries()]
        .filter(([, count]) => count > 1)
        .map(([fieldName, count]) => `${fieldName} (${count}x)`);
    expect(repeated).toEqual([], {
        message:
            "these computes read a computed field declared after them, so they run " +
            "once against its default and again once it settles — declare the " +
            "dependency first",
    });
});
