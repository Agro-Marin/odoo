import { defineMailModels, start as start2 } from "@mail/../tests/mail_test_helpers";
import { makeStore, Record, Store } from "@mail/core/common/record";
import { fields } from "@mail/model/misc";
import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { reactive, toRaw } from "@odoo/owl";
import { mockService } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

describe.current.tags("desktop");
defineMailModels();

const localRegistry = registry.category("discuss.model.test");

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

function defineContactTask() {
    (class Contact extends Record {
        static id = "name";
        name;
        tasks = fields.Many("Task", { inverse: "contact" });
        mainTask = fields.One("Task");
    }).register(localRegistry);
    (class Task extends Record {
        static id = "name";
        name;
        label = fields.Attr("");
        contact = fields.One("Contact", { inverse: "tasks" });
    }).register(localRegistry);
}

test("add() returns reactive proxies, never raw records", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    const added = john.tasks.add(t1);
    expect(toRaw(added)).not.toBe(added);
    expect(added.eq(t1)).toBe(true);
    const mainTaskList = toRaw(john)._raw.mainTask._proxy;
    const addedOne = mainTaskList.add(t1);
    expect(toRaw(addedOne)).not.toBe(addedOne);
    expect(addedOne.eq(t1)).toBe(true);
});

test("add() reports one record per argument, including already-present ones", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    const t2 = store.Task.insert("t2");
    john.tasks.add(t1);
    expect(john.tasks.add(t1)?.eq(t1)).toBe(true);
    const res = john.tasks.add(t1, t2);
    expect(res.length).toBe(2);
    expect(res[0].eq(t1)).toBe(true);
    expect(res[1].eq(t2)).toBe(true);
});

test("growing a record list through length is rejected", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    john.tasks.add(store.Task.insert("t1"));
    expect(() => {
        john.tasks.length = 3;
    }).toThrow(/Cannot grow record list/);
    expect(john.tasks.length).toBe(1);
    expect(john.tasks.data.length).toBe(1);
});

test("shrinking a record list through length detaches the removed records", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    const t2 = store.Task.insert("t2");
    john.tasks.add(t1, t2);
    john.tasks.length = 1;
    expect(john.tasks.length).toBe(1);
    expect(john.tasks.data.length).toBe(1);
    expect(t1.contact.eq(john)).toBe(true);
    expect(t2.contact).toBe(undefined);
});

test("a record handed out raw would silently lose reactivity", async () => {
    defineContactTask();
    const store = await start();
    const t1 = store.Task.insert("t1");
    let rawFires = 0;
    const observedRaw = reactive(toRaw(t1)._raw, () => rawFires++);
    void observedRaw.label;
    let proxyFires = 0;
    const observedProxy = reactive(t1, () => proxyFires++);
    void observedProxy.label;
    t1.label = "changed";
    expect(proxyFires).toBe(1);
    expect(rawFires).toBe(0);
});

test("growing `data` past the real membership exposes phantom members", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    john.tasks.add(store.Task.insert("t1"));
    toRaw(john)._raw.tasks._proxy.data.length = 3;
    expect(john.tasks.at(1)).toBe(undefined);
    expect([...john.tasks]).toHaveLength(3);
    expect([...john.tasks].filter(Boolean)).toHaveLength(1);
});

test("add() edge shapes: no args, nullish entries, plain data", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    expect(john.tasks.add()).toEqual([]);
    expect(john.tasks.add(undefined)).toBe(undefined);
    expect(john.tasks.data).toHaveLength(0);
    const mixed = john.tasks.add(undefined, t1);
    expect(mixed).toHaveLength(2);
    expect(mixed[0]).toBe(undefined);
    expect(mixed[1].eq(t1)).toBe(true);
    const fromData = john.tasks.add("t2");
    expect(toRaw(fromData)).not.toBe(fromData);
    expect(fromData.name).toBe("t2");
});

test("splice() with a negative start removes and tears down the same record", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const [t1, t2, t3] = ["t1", "t2", "t3"].map((name) => store.Task.insert(name));
    john.tasks.add(t1, t2, t3);
    expect(john.tasks.map((t) => t.name)).toEqual(["t1", "t2", "t3"]);
    john.tasks.splice(-1, 1);
    expect(john.tasks.map((t) => t.name)).toEqual(["t1", "t2"]);
    expect(t3.contact).toBe(undefined);
    expect(t1.contact.name).toBe("John");
});

test("splice() clamps start and deleteCount like Array.prototype.splice", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const [t1, t2, t3] = ["t1", "t2", "t3"].map((name) => store.Task.insert(name));
    john.tasks.add(t1, t2, t3);
    john.tasks.splice(-100, 1);
    expect(john.tasks.map((t) => t.name)).toEqual(["t2", "t3"]);
    expect(t1.contact).toBe(undefined);
    john.tasks.splice(1, 100);
    expect(john.tasks.map((t) => t.name)).toEqual(["t2"]);
    expect(t3.contact).toBe(undefined);
    john.tasks.splice(5, 1);
    expect(john.tasks.map((t) => t.name)).toEqual(["t2"]);
});
