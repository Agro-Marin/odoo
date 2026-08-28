import { defineMailModels, start as start2 } from "@mail/../tests/mail_test_helpers";
import { makeStore, Record, Store } from "@mail/core/common/record";
import { fields } from "@mail/model/misc";
import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { mockService } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

describe.current.tags("desktop");
defineMailModels();

const localRegistry = registry.category("discuss.model.invariants");
const badRegistry = registry.category("discuss.model.invariants.rejected");

beforeEach(() => {
    Record.register(localRegistry);
    Store.register(localRegistry);
    Record.register(badRegistry);
    Store.register(badRegistry);
    mockService("store", (env) => makeStore(env, { localRegistry }));
});
afterEach(() => {
    for (const reg of [localRegistry, badRegistry]) {
        for (const [modelName] of reg.getEntries()) {
            reg.remove(modelName);
        }
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
    expect(Object.keys(payload).join(",")).toBe(keysBefore);
    expect(t1.members).toHaveLength(1);
    expect(t1.members[0].name).toBe("m1");
    expect(t1.members[0].thread.eq(t1)).toBe(true);
    const t2 = store.Thread.insert({ name: "T2", members: [payload] });
    expect(t2.members[0].thread.eq(t2)).toBe(true);
});

test("an inverse naming no field on the target model is refused at boot", async () => {
    const env = await start2();
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", { inverse: "typoedThread" });
    }).register(badRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread");
    }).register(badRegistry);
    expect(() => makeStore(env, { localRegistry: badRegistry })).toThrow(
        'Field Thread.members declares inverse "typoedThread", but Member has no fields.One()/fields.Many() named "typoedThread"',
    );
});

test("an inverse naming a plain attribute on the target model is refused at boot", async () => {
    const env = await start2();
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", { inverse: "thread" });
    }).register(badRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.Attr(undefined);
    }).register(badRegistry);
    expect(() => makeStore(env, { localRegistry: badRegistry })).toThrow(
        'Field Thread.members declares inverse "thread", but Member has no fields.One()/fields.Many() named "thread"',
    );
});

test("a one-sided inverse, declared only on the owning model, still boots", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", { inverse: "thread" });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread");
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert({ name: "T1", members: [{ name: "m1" }] });
    expect(thread.members).toHaveLength(1);
    expect(store.Member.get({ name: "m1" }).thread.eq(thread)).toBe(true);
});

test("_DELETE is resolved per identity in payload order, not deferred past it", async () => {
    (class Doc extends Record {
        static id = "name";
        name;
        label;
    }).register(localRegistry);
    const store = await start();
    store.Doc.insert({ name: "d1", label: "before" });
    store.insert({
        Doc: [
            { name: "d1", _DELETE: true },
            { name: "d1", label: "after" },
        ],
    });
    expect(store.Doc.get({ name: "d1" })?.label).toBe("after");
    store.insert({
        Doc: [
            { name: "d1", label: "again" },
            { name: "d1", _DELETE: true },
        ],
    });
    expect(store.Doc.get({ name: "d1" })).toBe(undefined);
    store.Doc.insert({ name: "d2", label: "x" });
    store.insert({ Doc: [{ name: "d2", _DELETE: true }, { name: "d3" }] });
    expect(store.Doc.get({ name: "d2" })).toBe(undefined);
    expect(Boolean(store.Doc.get({ name: "d3" }))).toBe(true);
});

test("one model's rows failing does not abort the models after it", async () => {
    (class Boom extends Record {
        static id = "name";
        name;
        bad = fields.Attr(undefined, {
            compute() {
                if (this.name === "explodes") {
                    throw new Error("compute exploded");
                }
                return 1;
            },
        });
    }).register(localRegistry);
    (class Late extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    store.logErrors = false;
    expect(() =>
        store.insert({
            Boom: [{ name: "explodes" }],
            Late: [{ name: "l1" }, { name: "l2" }],
        }),
    ).toThrow("compute exploded");
    expect(Boolean(store.Late.get({ name: "l1" }))).toBe(true);
    expect(Boolean(store.Late.get({ name: "l2" }))).toBe(true);
});

test("logErrors does not decide whether an error throws", async () => {
    (class Boom extends Record {
        static id = "name";
        name;
        bad = fields.Attr(undefined, {
            compute() {
                throw new Error("compute exploded");
            },
        });
    }).register(localRegistry);
    const store = await start();
    store.logErrors = false;
    expect(() => store.Boom.insert({ name: "a" })).toThrow("compute exploded");
    store.logErrors = true;
    expect(() => store.Boom.insert({ name: "b" })).toThrow("compute exploded");
});

test("toData() emits one row per record when several fields reach the same one", async () => {
    (class Root extends Record {
        static id = "name";
        name;
        left = fields.One("Leaf");
        right = fields.One("Leaf");
    }).register(localRegistry);
    (class Leaf extends Record {
        static id = "name";
        name;
        tag;
    }).register(localRegistry);
    const store = await start();
    const leaf = store.Leaf.insert({ name: "shared", tag: "t" });
    const root = store.Root.insert({ name: "R", left: leaf, right: leaf });
    const data = root.toData(["left", "right"]);
    expect(data.Leaf).toHaveLength(1);
    expect(data.Leaf[0].name).toBe("shared");
    expect(data.Leaf[0].tag).toBe("t");
    expect(data.Root).toHaveLength(1);
});

test("a model named after a store property is refused at boot", async () => {
    const env = await start2();
    (class Env extends Record {
        static _name = "env";
        static id = "name";
        name;
    }).register(badRegistry);
    expect(() => makeStore(env, { localRegistry: badRegistry })).toThrow(
        "There must be no duplicated Model Names (duplicate found: env)",
    );
});

test("a relation naming an unregistered target model is refused at boot", async () => {
    const env = await start2();
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Ghost");
    }).register(badRegistry);
    expect(() => makeStore(env, { localRegistry: badRegistry })).toThrow(
        "No target model Ghost exists",
    );
});

test("an inverse pair disagreeing on the target model is refused at boot", async () => {
    const env = await start2();
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", { inverse: "thread" });
    }).register(badRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.One("Other", { inverse: "members" });
    }).register(badRegistry);
    (class Other extends Record {
        static id = "name";
        name;
        members = fields.Many("Member");
    }).register(badRegistry);
    expect(() => makeStore(env, { localRegistry: badRegistry })).toThrow(
        /has wrong targetModel/,
    );
});

test("an inverse pair disagreeing on the inverse name is refused at boot", async () => {
    const env = await start2();
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", { inverse: "thread" });
        watchers = fields.Many("Member");
    }).register(badRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread", { inverse: "watchers" });
    }).register(badRegistry);
    expect(() => makeStore(env, { localRegistry: badRegistry })).toThrow(
        /has wrong inverse/,
    );
});
