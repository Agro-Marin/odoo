// @ts-check
import { defineMailModels, start as start2 } from "@mail/../tests/mail_test_helpers";
import { makeStore, Record, Store } from "@mail/core/common/record";
import { fields } from "@mail/model/misc";
import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { reactive, toRaw } from "@odoo/owl";
import { mockService, patchWithCleanup } from "@web/../tests/web_test_helpers";
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
        tasks = fields.Many(/** @type {string} */ ("Task"), { inverse: "contact" });
        mainTask = fields.One(/** @type {string} */ ("Task"));
    }).register(localRegistry);
    (class Task extends Record {
        static id = "name";
        name;
        label = fields.Attr("");
        contact = fields.One(/** @type {string} */ ("Contact"), { inverse: "tasks" });
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
    store.logErrors = false;
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

test("assigning at an index swaps the record and keeps the inverse in step", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    const t2 = store.Task.insert("t2");
    john.tasks.add(t1);
    expect(t1.contact.eq(john)).toBe(true);

    john.tasks[0] = t2;
    expect(john.tasks.length).toBe(1);
    expect(john.tasks[0].eq(t2)).toBe(true);
    expect(t2.contact.eq(john)).toBe(true);
    expect(t1.contact).toBe(undefined);
});

test("assigning the record already at that index changes nothing", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    john.tasks.add(t1);
    Record.onChange(john, "tasks", () => expect.step("tasks changed"));

    john.tasks[0] = t1;
    expect(john.tasks.length).toBe(1);
    expect(john.tasks[0].eq(t1)).toBe(true);
    expect.verifySteps([]);
});

test("assigning a nullish value at an index is rejected", async () => {
    defineContactTask();
    const store = await start();
    store.logErrors = false;
    const john = store.Contact.insert("John");
    john.tasks.add(store.Task.insert("t1"));
    for (const nullish of [undefined, null, false]) {
        expect(() => {
            john.tasks[0] = nullish;
        }).toThrow(/use delete\(\)\/splice\(\) to remove records/);
    }
    expect(john.tasks.length).toBe(1);
});

test("assigning one past the end appends rather than being out of range", async () => {
    defineContactTask();
    const store = await start();
    store.logErrors = false;
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    const t2 = store.Task.insert("t2");
    john.tasks.add(t1);

    john.tasks[1] = t2;
    expect(john.tasks.length).toBe(2);
    expect(john.tasks[1].eq(t2)).toBe(true);
    expect(t2.contact.eq(john)).toBe(true);
    expect(() => {
        john.tasks[5] = store.Task.insert("t3");
    }).toThrow(/out of range/);
});

/** @param {any} store */
function stepRelationWrites(store) {
    patchWithCleanup(toRaw(store)._raw._, {
        updateRelation(record, fieldName, value) {
            expect.step(`${record.localId}/${fieldName}`);
            return super.updateRelation(record, fieldName, value);
        },
    });
}

test("add() and delete() write the inverse relation exactly once", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    stepRelationWrites(store);
    john.tasks.add(t1);
    expect.verifySteps(["Task,t1/contact"]);
    expect(t1.contact.eq(john)).toBe(true);
    john.tasks.delete(t1);
    expect.verifySteps(["Task,t1/contact"]);
    expect(t1.contact).toBe(undefined);
    expect(john.tasks).toHaveLength(0);
});

test("assigning a relation writes each inverse exactly once", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    const t2 = store.Task.insert("t2");
    stepRelationWrites(store);
    john.tasks = [t1, t2];
    expect.verifySteps(["Contact,John/tasks", "Task,t1/contact", "Task,t2/contact"]);
    john.tasks = [t2];
    expect.verifySteps(["Contact,John/tasks", "Task,t1/contact"]);
    expect(t1.contact).toBe(undefined);
    expect(t2.contact.eq(john)).toBe(true);
    expect(john.tasks.map((t) => t.name)).toEqual(["t2"]);
});

test("moving a one-field to another owner detaches it from the previous owner once", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const jane = store.Contact.insert("Jane");
    const t1 = store.Task.insert("t1");
    john.tasks.add(t1);
    stepRelationWrites(store);
    t1.contact = jane;
    expect.verifySteps(["Task,t1/contact", "Contact,Jane/tasks", "Contact,John/tasks"]);
    expect(john.tasks).toHaveLength(0);
    expect(jane.tasks.map((t) => t.name)).toEqual(["t1"]);
    expect(t1.contact.eq(jane)).toBe(true);
});

test("pop(), shift() and splice() return the removed records", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const [t1, t2, t3, t4] = ["t1", "t2", "t3", "t4"].map((name) =>
        store.Task.insert(name),
    );
    john.tasks.add(t1, t2, t3, t4);
    expect(john.tasks.pop().eq(t4)).toBe(true);
    expect(john.tasks.shift().eq(t1)).toBe(true);
    const removed = john.tasks.splice(0, 1);
    expect(removed).toHaveLength(1);
    expect(removed[0].eq(t2)).toBe(true);
    expect(john.tasks.map((t) => t.name)).toEqual(["t3"]);
    for (const task of [t1, t2, t4]) {
        expect(task.contact).toBe(undefined);
    }
    expect(t3.contact.eq(john)).toBe(true);
    expect(john.tasks.pop().eq(t3)).toBe(true);
    expect(john.tasks.pop()).toBe(undefined);
});

test("iterator- and scalar-returning Array methods read `data` without materializing", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    const t2 = store.Task.insert("t2");
    john.tasks.add(t1);
    const values = john.tasks.values();
    const keys = john.tasks.keys();
    const entries = john.tasks.entries();
    john.tasks.add(t2);
    expect([...values].map((t) => t.name)).toEqual(["t1", "t2"]);
    expect([...keys]).toEqual([0, 1]);
    expect([...entries].map(([i, t]) => `${i}:${t.name}`)).toEqual(["0:t1", "1:t2"]);
    expect(john.tasks.lastIndexOf(t2)).toBe(1);
    expect(john.tasks.lastIndexOf(store.Task.insert("t3"))).toBe(-1);
    expect(john.tasks.join("|").split("|")).toHaveLength(2);
    expect(john.tasks.reduceRight((acc, t) => acc + t.name, "")).toBe("t2t1");
});

test("array-returning Array methods copy once and leave the list untouched", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    const t1 = store.Task.insert("t1");
    const t2 = store.Task.insert("t2");
    john.tasks.add(t1, t2);
    const names = (tasks) => tasks.map((t) => t.name);
    expect(names(john.tasks.toReversed())).toEqual(["t2", "t1"]);
    expect(names(john.tasks.toSorted((a, b) => b.name.localeCompare(a.name)))).toEqual([
        "t2",
        "t1",
    ]);
    expect(names(john.tasks.with(0, t2))).toEqual(["t2", "t2"]);
    expect(names(john.tasks.toSpliced(0, 1))).toEqual(["t2"]);
    expect(john.tasks.flatMap((t) => [t.name, t.name])).toEqual([
        "t1",
        "t1",
        "t2",
        "t2",
    ]);
    expect(names(john.tasks)).toEqual(["t1", "t2"]);
    expect(t1.contact.eq(john)).toBe(true);
});

test("an Array method with no record-list reimplementation throws instead of copying", async () => {
    defineContactTask();
    const store = await start();
    const john = store.Contact.insert("John");
    john.tasks.add(store.Task.insert("t1"));
    patchWithCleanup(Array.prototype, {
        hootProbe() {
            return "materialized";
        },
    });
    expect(() => john.tasks.hootProbe()).toThrow(
        /Array\.prototype\.hootProbe\(\) is not supported/,
    );
    expect(/** @type {number[] & {hootProbe(): string}} */ ([1]).hootProbe()).toBe(
        "materialized",
    );
});

test("the membership set of a record list follows every mutator", async () => {
    (class Team extends Record {
        static id = "id";
        id;
        members = fields.Many(/** @type {string} */ ("Person"), { inverse: "team" });
        lead = fields.One(/** @type {string} */ ("Person"), { inverse: "leadOf" });
    }).register(localRegistry);
    (class Person extends Record {
        static id = "id";
        id;
        team = fields.One(/** @type {string} */ ("Team"));
        leadOf = fields.One(/** @type {string} */ ("Team"));
    }).register(localRegistry);
    const store = await start();
    const team = store.Team.insert({ id: 1 });
    const people = store.Person.insert([1, 2, 3, 4, 5, 6].map((id) => ({ id })));
    const raw = (list) => toRaw(list)._raw;
    const agrees = (list) => {
        const rawList = raw(list);
        for (const person of people) {
            const localId = toRaw(person)._raw.localId;
            expect(rawList._.has(rawList, localId)).toBe(
                rawList.data.includes(localId),
            );
        }
        expect(rawList._.localIdSet?.size ?? rawList.data.length).toBe(
            rawList.data.length,
        );
    };
    team.members.add(people[0], people[1]);
    agrees(team.members);
    people[2].team = team; // inverse path (addNoinv)
    agrees(team.members);
    team.members.add(people[2]); // already a member: no duplicate
    expect(team.members.length).toBe(3);
    team.members.splice(1, 1, people[3], people[4]);
    agrees(team.members);
    team.members.delete(people[0]);
    agrees(team.members);
    people[3].team = undefined; // inverse removal (deleteNoinv)
    agrees(team.members);
    team.members = [people[5], people[1]]; // assign
    agrees(team.members);
    team.lead = people[0];
    team.lead = people[1]; // One replace
    agrees(raw(team).lead);
    team.members.clear();
    agrees(team.members);
    expect(team.members.length).toBe(0);
    team.members.unshift(people[4]);
    team.members.push(people[5]);
    agrees(team.members);
    expect(team.members.map((p) => p.id)).toEqual([5, 6]);
});
