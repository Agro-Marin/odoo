import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { Store } from "@mail/core/common/store_service";
import { describe, expect, test } from "@odoo/hoot";
import {
    getService,
    mockService,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("reading displayName does not reorder channel_name_member_ids in place", async () => {
    await start();
    const store = getService("mail.store");
    // members are supplied out of id order so an in-place sort is observable
    const thread = store.Thread.insert({
        id: 1,
        model: "discuss.channel",
        channel_type: "group",
        channel_name_member_ids: [
            { id: 30, guest_id: { id: 3, name: "Charlie" } },
            { id: 10, guest_id: { id: 1, name: "Alice" } },
            { id: 20, guest_id: { id: 2, name: "Bob" } },
        ],
    });
    expect(thread.channel_name_member_ids.map((member) => member.id)).toEqual([
        30, 10, 20,
    ]);

    // the label is still ordered by member id for display...
    expect(thread.displayName).toBe("Alice, Bob, and Charlie");

    // ...but the stored reactive Many must keep its order: displayName runs on
    // the render path, so a `.sort()` on the field would churn reactivity.
    expect(thread.channel_name_member_ids.map((member) => member.id)).toEqual([
        30, 10, 20,
    ]);
});

test("getOrFetch resolves (never rejects) when the channel fetch fails", async () => {
    await start();
    const store = getService("mail.store");
    patchWithCleanup(Store.prototype, {
        fetchChannel() {
            return Promise.reject(new Error("boom"));
        },
    });
    let rejected = false;
    let result = "unset";
    await store.Thread.getOrFetch({ id: 999, model: "discuss.channel" }).then(
        (thread) => (result = thread),
        () => (rejected = true),
    );
    // a rejection here surfaces as an unhandled rejection in the fire-and-forget
    // callers, so a failed fetch must resolve `undefined` for their null-checks
    expect(rejected).toBe(false);
    expect(result).toBe(undefined);
});

test("rename reverts the optimistic name when the server call fails", async () => {
    await start();
    const store = getService("mail.store");
    const thread = store.Thread.insert({
        id: 1,
        model: "discuss.channel",
        channel_type: "channel",
        name: "Original",
    });
    mockService("orm", {
        call() {
            return Promise.reject(new Error("boom"));
        },
    });
    let threw = false;
    await thread.rename("New name").catch(() => (threw = true));
    // the error still propagates, but the optimistic write must be rolled back
    // so the UI does not diverge from the server until a reload
    expect(threw).toBe(true);
    expect(thread.name).toBe("Original");
});

test("notifyDescriptionToServer reverts the optimistic description on failure", async () => {
    await start();
    const store = getService("mail.store");
    const thread = store.Thread.insert({
        id: 1,
        model: "discuss.channel",
        channel_type: "channel",
        description: "Old description",
    });
    mockService("orm", {
        call() {
            return Promise.reject(new Error("boom"));
        },
    });
    let threw = false;
    await thread
        .notifyDescriptionToServer("New description")
        .catch(() => (threw = true));
    expect(threw).toBe(true);
    expect(thread.description).toBe("Old description");
});
