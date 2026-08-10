import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { getService } from "@web/../tests/web_test_helpers";

/**
 * `MessagingMenu.threads` used to derive itself by scanning `Thread.records`, which
 * made it an observer of the record keys plus `displayToSelf` and
 * `needactionMessages` on *every* thread in the store. Loading threads then
 * cost O(n) per thread: measured at ~1.3ms per recompute with 200 threads
 * loaded, so ~13ms to insert ten more.
 *
 * Eligibility is now maintained per thread
 * (@see Thread.menuAsThreadCandidate), so a thread that cannot appear in
 * the menu does not disturb it at all. These tests pin the scaling property,
 * not the timing — a rescan would fail them on any machine.
 */
describe.current.tags("desktop");
defineMailModels();

/** Count `MessagingMenu.threads` recomputes while `fn` runs. */
async function countRecomputes(store, fn) {
    const Model = store.Thread._rawStore.Models.MessagingMenu;
    const compute = Model._.fieldsCompute.get("threads");
    let runs = 0;
    Model._.fieldsCompute.set("threads", function () {
        runs++;
        return compute.call(this);
    });
    try {
        await fn();
    } finally {
        Model._.fieldsCompute.set("threads", compute);
    }
    return runs;
}

test("threads that cannot appear in the menu do not recompute it", async () => {
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
        message: "inserting non-candidate threads must not touch MessagingMenu.threads",
    });
});

test("a thread becoming eligible enters the menu, and leaving removes it", async () => {
    await startServer();
    await start();
    const store = getService("mail.store");
    const thread = store.Thread.insert({
        model: "discuss.channel",
        id: 1,
        name: "chan",
    });
    expect(thread.notIn(store.messagingMenu.threads)).toBe(true);
    thread.displayToSelf = true;
    expect(thread.in(store.messagingMenu.threadCandidates)).toBe(true);
    expect(thread.in(store.messagingMenu.threads)).toBe(true);
    thread.displayToSelf = false;
    expect(thread.notIn(store.messagingMenu.threadCandidates)).toBe(true);
    expect(thread.notIn(store.messagingMenu.threads)).toBe(true);
});

test("the menu search term still filters candidates", async () => {
    await startServer();
    await start();
    const store = getService("mail.store");
    const alpha = store.Thread.insert({
        model: "discuss.channel",
        id: 1,
        name: "Alpha",
        display_name: "Alpha",
    });
    const beta = store.Thread.insert({
        model: "discuss.channel",
        id: 2,
        name: "Beta",
        display_name: "Beta",
    });
    alpha.displayToSelf = true;
    beta.displayToSelf = true;
    expect(store.messagingMenu.threads).toHaveLength(2);
    store.discuss.searchTerm = "alph";
    expect(alpha.in(store.messagingMenu.threads)).toBe(true);
    expect(beta.notIn(store.messagingMenu.threads)).toBe(true);
});
