import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { getService } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

async function countRecomputes(store, fn) {
    const Model = store.Thread._rawStore.Models.Store;
    const compute = Model._.fieldsCompute.get("globalCounter");
    let runs = 0;
    Model._.fieldsCompute.set("globalCounter", function () {
        runs++;
        return compute.call(this);
    });
    try {
        await fn();
    } finally {
        Model._.fieldsCompute.set("globalCounter", compute);
    }
    return runs;
}

test("threads with nothing pending do not recompute the global counter", async () => {
    await startServer();
    await start();
    const store = getService("mail.store");
    for (let i = 1; i <= 50; i++) {
        store.Thread.insert({ model: "discuss.channel", id: i, name: `chan ${i}` });
    }
    const runs = await countRecomputes(store, () => {
        for (let i = 51; i <= 60; i++) {
            store.Thread.insert({ model: "discuss.channel", id: i, name: `chan ${i}` });
        }
    });
    expect(runs).toBe(0, {
        message:
            "inserting channels with no unread/needaction must not touch the badge",
    });
});

test("a needaction on one channel does not re-read every other channel", async () => {
    await startServer();
    await start();
    const store = getService("mail.store");
    const threads = [];
    for (let i = 1; i <= 50; i++) {
        threads.push(
            store.Thread.insert({ model: "discuss.channel", id: i, name: `chan ${i}` }),
        );
    }
    threads[0].message_needaction_counter = 1;
    expect(threads[0].in(store.counterChannels)).toBe(true);
    expect(threads[1].notIn(store.counterChannels)).toBe(true);
    threads[0].message_needaction_counter = 0;
    expect(threads[0].notIn(store.counterChannels)).toBe(true);
});

test("the counted set still drives the badge value", async () => {
    await startServer();
    await start();
    const store = getService("mail.store");
    const before = store.globalCounter;
    const thread = store.Thread.insert({
        model: "discuss.channel",
        id: 1,
        name: "chan",
    });
    expect(store.globalCounter).toBe(before, {
        message: "a channel with nothing pending changes nothing",
    });
    thread.message_needaction_counter = 3;
    expect(thread.in(store.counterChannels)).toBe(true);
    expect(store.globalCounter).not.toBe(before + 3);
});
