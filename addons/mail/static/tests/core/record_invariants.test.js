import { defineMailModels, start as start2 } from "@mail/../tests/mail_test_helpers";
import { makeStore, Record, Store } from "@mail/core/common/record";
import { fields } from "@mail/model/misc";
import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { mockService } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

describe.current.tags("desktop");
defineMailModels();

const localRegistry = registry.category("discuss.model.invariants");

beforeEach(() => {
    Record.register(localRegistry);
    Store.register(localRegistry);
    mockService("store", (env) => makeStore(env, { localRegistry }));
});
afterEach(() => {
    for (const [modelName] of localRegistry.getEntries()) {
        localRegistry.remove(modelName);
    }
});

async function start() {
    const env = await start2();
    return env.services.store;
}

test("insert() must not mutate a caller-supplied relation-data payload", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", { inverse: "thread" });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread", { inverse: "members" });
    }).register(localRegistry);
    const store = await start();
    const payload = { name: "m1" };
    const keysBefore = Object.keys(payload).join(",");
    const t1 = store.Thread.insert({ name: "T1", members: [payload] });
    expect(Object.keys(payload).join(",")).toBe(keysBefore); // no `thread` key leaked in
    // the relation still wired up correctly despite the clone:
    expect(t1.members).toHaveLength(1);
    expect(t1.members[0].name).toBe("m1");
    expect(t1.members[0].thread.eq(t1)).toBe(true);
    // reusing the same payload for a different parent must not carry stale state:
    const t2 = store.Thread.insert({ name: "T2", members: [payload] });
    expect(t2.members[0].thread.eq(t2)).toBe(true);
});
