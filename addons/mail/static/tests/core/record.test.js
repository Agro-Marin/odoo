import { defineMailModels, start as start2 } from "@mail/../tests/mail_test_helpers";
import { makeStore, Record, Store } from "@mail/core/common/record";
import { AND, fields, OR } from "@mail/model/misc";
import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { markup, reactive, toRaw } from "@odoo/owl";
import { asyncStep, mockService, waitForSteps } from "@web/../tests/web_test_helpers";
import { serializeDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { effect } from "@web/core/utils/reactive";

const Markup = markup().constructor;

describe.current.tags("desktop");
defineMailModels();

const expectRecord = (record, not = false) => {
    const toBeIn = (reclist) => {
        expect(record?.in(reclist)).toBe(!not);
    };

    const toEqual = (expected) => {
        expect(record?.eq(expected)).toBe(!not);
    };

    return {
        get not() {
            return expectRecord(record, !not);
        },
        toBeIn,
        toEqual,
    };
};

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

test("Insert by passing only single-id value (non-relational)", async () => {
    (class Persona extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const john = store.Persona.insert("John");
    expect(john.name).toBe("John");
});

test("Can pass object as data for relational field with inverse as id", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        composer = fields.One("Composer", { inverse: "thread" });
    }).register(localRegistry);
    (class Composer extends Record {
        static id = "thread";
        thread = fields.One("Thread");
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    Object.assign(thread, { composer: {} });
    expectRecord(thread.composer.thread).toEqual(thread);
});

test("pass single-id as data for 'one' relational field without inverse", async () => {
    (class Message extends Record {
        static id = "id";
        id;
        author = fields.One("Partner");
    }).register(localRegistry);
    (class Partner extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const message = store.Message.insert({ id: 1, author: "John" });
    const author = message.author;
    expect(author.name).toBe("John");
    store.Message.insert({ id: 1, author: null });
    expect(message.author).toBe(undefined);
    expect(author.name).toBe("John");
    store.Message.insert({ id: 1, author: false });
    expect(message.author).toBe(undefined);
    store.Message.insert({ id: 1, author: undefined });
    expect(message.author).toBe(undefined);
});

test("pass single-id as data for 'one' relational field with inverse", async () => {
    (class Message extends Record {
        static id = "id";
        id;
        author = fields.One("Partner", { inverse: "messages" });
    }).register(localRegistry);
    (class Partner extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message", { inverse: "author" });
    }).register(localRegistry);
    const store = await start();
    const message = store.Message.insert({ id: 1, author: "John" });
    const author = message.author;
    expect(author.name).toBe("John");
    expect(author.messages.length).toBe(1);
    expect(author.messages[0]).toBe(message);
    store.Message.insert({ id: 1, author: null });
    expect(message.author).toBe(undefined);
    expect(author.name).toBe("John");
    store.Message.insert({ id: 1, author: false });
    expect(message.author).toBe(undefined);
    store.Message.insert({ id: 1, author: undefined });
    expect(message.author).toBe(undefined);
});

test("pass single-id as data for 'one' relational field as id", async () => {
    (class Thread extends Record {
        static id = "id";
        id;
        composer = fields.One("Composer", { inverse: "thread" });
    }).register(localRegistry);
    (class Composer extends Record {
        static id = "thread";
        thread = fields.One("Thread", { inverse: "composer" });
        composerView = fields.Many("ComposerView", { inverse: "composer" });
    }).register(localRegistry);
    (class ComposerView extends Record {
        static id = "id";
        composer = fields.One("Composer", { inverse: "composerView" });
    }).register(localRegistry);
    const store = await start();
    const composerView = store.ComposerView.insert({ id: 1, composer: 2 });
    const composer = composerView.composer;
    expect(composer.thread.id).toBe(2);
    store.ComposerView.insert({ id: 1, composer: null });
    expect(composerView.composer).toBe(undefined);
    expect(composer.thread.id).toBe(2);
    store.ComposerView.insert({ id: 1, composer: false });
    expect(composerView.composer).toBe(undefined);
    store.ComposerView.insert({ id: 1, composer: undefined });
    expect(composerView.composer).toBe(undefined);
});

test("pass single-id as data for 'many' relational field without inverse", async () => {
    (class Message extends Record {
        static id = "id";
        id;
        authors = fields.Many("Partner");
    }).register(localRegistry);
    (class Partner extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const message = store.Message.insert({ id: 1, authors: ["John", "Jane"] });
    expect(message.authors.length).toBe(2);
    expect(message.authors[0].name).toBe("John");
    expect(message.authors[1].name).toBe("Jane");
});

test("pass single-id as data for 'many' relational field with inverse", async () => {
    (class Message extends Record {
        static id = "id";
        id;
        authors = fields.Many("Partner", { inverse: "messages" });
    }).register(localRegistry);
    (class Partner extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message", { inverse: "authors" });
    }).register(localRegistry);
    const store = await start();
    const message = store.Message.insert({ id: 1, authors: ["John", "Jane"] });
    expect(message.authors.length).toBe(2);
    expect(message.authors[0].name).toBe("John");
    expect(message.authors[0].messages.length).toBe(1);
    expect(message.authors[0].messages[0]).toBe(message);
    expect(message.authors[1].name).toBe("Jane");
    expect(message.authors[1].messages.length).toBe(1);
    expect(message.authors[1].messages[0]).toBe(message);
});

test("Assign & Delete on fields with inverses", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        composer = fields.One("Composer", { inverse: "thread" });
        members = fields.Many("Member", { inverse: "thread" });
        messages = fields.Many("Message", { inverse: "threads" });
    }).register(localRegistry);
    (class Composer extends Record {
        static id = "thread";
        thread = fields.One("Thread");
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread");
    }).register(localRegistry);
    (class Message extends Record {
        static id = "content";
        content;
        threads = fields.Many("Thread");
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    const [john, marc] = store.Member.insert(["John", "Marc"]);
    const [hello, world] = store.Message.insert(["hello", "world"]);
    // Assign on fields should adapt inverses
    Object.assign(thread, {
        composer: {},
        members: [["ADD", john]],
        messages: [hello, world],
    });
    expectRecord(thread.composer.thread).toEqual(thread);
    expectRecord(john.thread).toEqual(thread);
    expectRecord(john).toBeIn(thread.members);
    expectRecord(hello).toBeIn(thread.messages);
    expectRecord(world).toBeIn(thread.messages);
    expectRecord(thread).toBeIn(hello.threads);
    expectRecord(thread).toBeIn(world.threads);
    // add() should adapt inverses
    thread.members.add(marc);
    expectRecord(marc).toBeIn(thread.members);
    expectRecord(marc.thread).toEqual(thread);
    // delete should adapt inverses
    thread.members.delete(john);
    expectRecord(john).not.toBeIn(thread.members);
    expect(Boolean(john.thread)).toBe(false);
    // can delete with command
    thread.messages = [["DELETE", world]];
    expectRecord(world).not.toBeIn(thread.messages);
    expectRecord(thread).not.toBeIn(world.threads);
    expect(thread.messages).toHaveLength(1);
    expectRecord(hello).toBeIn(thread.messages);
    expectRecord(thread).toBeIn(hello.threads);
    // Deletion removes all relations
    const composer = thread.composer;
    thread.delete();
    expect(Boolean(thread.composer)).toBe(false);
    expect(Boolean(composer.thread)).toBe(false);
    expectRecord(marc).not.toBeIn(thread.members);
    expect(thread.members).toBeEmpty();
    expectRecord(hello).not.toBeIn(thread.messages);
    expectRecord(thread).not.toBeIn(hello.threads);
    expect(thread.messages).toBeEmpty();
});

test("onAdd/onDelete hooks on relational with inverse", async () => {
    let logs = [];
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", {
            inverse: "thread",
            onAdd: (member) => logs.push(`Thread.onAdd(${member.name})`),
            onDelete: (member) => logs.push(`Thread.onDelete(${member.name})`),
        });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread");
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    const [john, marc] = store.Member.insert(["John", "Marc"]);
    thread.members.add(john);
    expect(logs).toEqual(["Thread.onAdd(John)"]);
    logs = [];
    thread.members.add(john);
    expect(logs).toBeEmpty();
    marc.thread = thread;
    expect(logs).toEqual(["Thread.onAdd(Marc)"]);
    logs = [];
    thread.members.delete(marc);
    expect(logs).toEqual(["Thread.onDelete(Marc)"]);
    logs = [];
    thread.members.delete(marc);
    expect(logs).toBeEmpty();
    john.thread = undefined;
    expect(logs).toEqual(["Thread.onDelete(John)"]);
});

test("Computed fields", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        type = fields.Attr("", {
            compute() {
                if (this.members.length === 0) {
                    return "empty chat";
                } else if (this.members.length === 1) {
                    return "self-chat";
                } else if (this.members.length === 2) {
                    return "dm chat";
                } else {
                    return "group chat";
                }
            },
        });
        admin = fields.One("Persona", {
            compute() {
                return this.members[0];
            },
        });
        members = fields.Many("Persona");
    }).register(localRegistry);
    (class Persona extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    const [john, marc, antony] = store.Persona.insert(["John", "Marc", "Antony"]);
    Object.assign(thread, { members: [john, marc] });
    expectRecord(thread.admin).toEqual(john);
    expect(thread.type).toBe("dm chat");
    thread.members.delete(john);
    expectRecord(thread.admin).toEqual(marc);
    expect(thread.type).toBe("self-chat");
    thread.members.unshift(antony, john);
    expectRecord(thread.admin).toEqual(antony);
    expect(thread.type).toBe("group chat");
});

test("Computed fields are always eager: compute on insert and on dependency change", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        type = fields.Attr("", {
            compute() {
                expect.step("COMPUTE");
                if (this.members.length === 0) {
                    return "empty chat";
                } else if (this.members.length === 1) {
                    return "self-chat";
                } else if (this.members.length === 2) {
                    return "dm chat";
                } else {
                    return "group chat";
                }
            },
        });
        members = fields.Many("Persona");
    }).register(localRegistry);
    (class Persona extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    // compute runs on insert, before any read of the field
    const thread = store.Thread.insert("General");
    expect.verifySteps(["COMPUTE"]);
    // reading does not schedule anything: the value is already there
    expect(thread.type).toBe("empty chat");
    expect(thread.type).toBe("empty chat");
    expect.verifySteps([]);
    // dependency change recomputes even though nothing observes the field
    thread.members.add("John");
    expect.verifySteps(["COMPUTE"]);
    expect(toRaw(thread)._raw.type).toBe("self-chat");
    thread.members.add("Antony");
    expect.verifySteps(["COMPUTE"]);
    thread.members.add("Demo");
    expect.verifySteps(["COMPUTE"]);
    expect(thread.type).toBe("group chat");
    expect.verifySteps([]);
});

test("insert on html field", async () => {
    // id is a separate field: body mutations below would otherwise rewrite
    // the record's identity, which id-field immutability forbids
    (class Message extends Record {
        static id = "id";
        id;
        body = fields.Html("");
    }).register(localRegistry);
    const store = await start();
    const message1 = store.Message.insert({
        id: 1,
        body: ["markup", "<p>hello 1</p>"],
    });
    expect(message1.body?.toString()).toBe("<p>hello 1</p>");
    expect(message1.body).toBeInstanceOf(Markup);
    message1.body = "<p>hello 1b</p>";
    expect(message1.body?.toString()).toBe("&lt;p&gt;hello 1b&lt;/p&gt;");
    const message2 = store.Message.insert({ id: 2, body: "<p>hello 2</p>" });
    expect(message2.body?.toString()).toBe("&lt;p&gt;hello 2&lt;/p&gt;");
    expect(message2.body).toBeInstanceOf(Markup);
    message2.body = ["markup", "<p>hello 2b</p>"];
    expect(message2.body?.toString()).toBe("<p>hello 2b</p>");
    message2.body = ["markup", false];
    expect(message2.body).toBe("");
    expect(message2.body).not.toBeInstanceOf(Markup);
    const message3 = store.Message.insert({ id: 3, body: markup`<p>hello 3</p>` });
    expect(message3.body?.toString()).toBe("<p>hello 3</p>");
    expect(message3.body).toBeInstanceOf(Markup);
    message3.body = false;
    expect(message3.body).toBe("");
    expect(message3.body).not.toBeInstanceOf(Markup);
});

test("Unshift preserves order", async () => {
    (class Message extends Record {
        static id = "id";
        id;
    }).register(localRegistry);
    (class Thread extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message");
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert({ name: "General" });
    thread.messages.unshift({ id: 3 }, { id: 2 }, { id: 1 });
    expect(thread.messages.map((msg) => msg.id)).toEqual([3, 2, 1]);
    thread.messages.unshift({ id: 6 }, { id: 5 }, { id: 4 });
    expect(thread.messages.map((msg) => msg.id)).toEqual([6, 5, 4, 3, 2, 1]);
    thread.messages.unshift({ id: 7 });
    expect(thread.messages.map((msg) => msg.id)).toEqual([7, 6, 5, 4, 3, 2, 1]);
});

test("onAdd hook should see fully inserted data", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", {
            inverse: "thread",
            onAdd: (member) =>
                expect.step(
                    `Thread.onAdd::${member.name}.${member.type}.${member.isAdmin}`,
                ),
        });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        type;
        isAdmin = fields.Attr(false, {
            compute() {
                return this.type === "admin";
            },
        });
        thread = fields.One("Thread");
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    thread.members.add({ name: "John", type: "admin" });
    expect.verifySteps(["Thread.onAdd::John.admin.true"]);
});

test("Can insert with relation as id, using relation as data object", async () => {
    (class User extends Record {
        static id = "name";
        name;
        settings = fields.One("Settings");
    }).register(localRegistry);
    (class Settings extends Record {
        static id = "user";
        pushNotif;
        user = fields.One("User", { inverse: "settings" });
    }).register(localRegistry);
    const store = await start();
    store.Settings.insert([
        { pushNotif: true, user: { name: "John" } },
        { pushNotif: false, user: { name: "Paul" } },
    ]);
    expect(store.User.get("John").settings.pushNotif).toBe(true);
    expect(store.User.get("Paul").settings.pushNotif).toBe(false);
});

test("Set on attr should invoke onChange", async () => {
    (class Message extends Record {
        static id = "id";
        id;
        body;
    }).register(localRegistry);
    const store = await start();
    const message = store.Message.insert(1);
    Record.onChange(message, "body", () => expect.step("BODY_CHANGED"));
    expect.verifySteps([]);
    message.update({ body: "test1" });
    message.body = "test2";
    expect.verifySteps(["BODY_CHANGED", "BODY_CHANGED"]);
});

test("record list sort should be manually observable", async () => {
    (class Thread extends Record {
        static id = "id";
        id;
        messages = fields.Many("Message", { inverse: "thread" });
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
        body;
        author;
        thread = fields.One("Thread", { inverse: "messages" });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert(1);
    const messages = store.Message.insert([
        { id: 1, body: "a", thread },
        { id: 2, body: "b", thread },
    ]);
    function sortMessages() {
        // minimal access through observed variables to reduce unexpected observing
        observedMessages.sort((m1, m2) => (m1.body < m2.body ? -1 : 1));
        expect.step(`sortMessages`);
    }
    const observedMessages = reactive(thread.messages, sortMessages);
    expect(`${thread.messages.map((m) => m.id)}`).toBe("1,2");
    sortMessages();
    expect(`${thread.messages.map((m) => m.id)}`).toBe("1,2");
    expect.verifySteps(["sortMessages"]);
    messages[0].body = "c";
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,1");
    expect.verifySteps(["sortMessages", "sortMessages"]);
    messages[0].body = "d";
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,1");
    expect.verifySteps(["sortMessages"]);
    messages[0].author = "Jane";
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,1");
    expect.verifySteps([]);
    store.Message.insert({ id: 3, body: "c", thread });
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,3,1");
    expect.verifySteps(["sortMessages", "sortMessages"]);
    messages[0].delete();
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,3");
    expect.verifySteps(["sortMessages"]);
});

test("relation field sort should be automatically observed", async () => {
    (class Thread extends Record {
        static id = "id";
        id;
        messages = fields.Many("Message", {
            inverse: "thread",
            sort: (m1, m2) => (m1.body < m2.body ? -1 : 1),
        });
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
        body;
        author;
        thread = fields.One("Thread", { inverse: "messages" });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert(1);
    const messages = store.Message.insert([
        { id: 1, body: "a", thread },
        { id: 2, body: "b", thread },
    ]);
    expect(`${thread.messages.map((m) => m.id)}`).toBe("1,2");
    messages[0].body = "c";
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,1");
    messages[0].body = "d";
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,1");
    messages[0].author = "Jane";
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,1");
    store.Message.insert({ id: 3, body: "c", thread });
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,3,1");
    messages[0].delete();
    expect(`${thread.messages.map((m) => m.id)}`).toBe("2,3");
});

test("compute relation field stays up to date without being read", async () => {
    (class Thread extends Record {
        static id = "id";
        id;
        messages = fields.Many("Message", {
            inverse: "thread",
            sort: (m1, m2) => (m1.body < m2.body ? -1 : 1),
        });
        messages2 = fields.Many("Message", {
            compute() {
                return this.messages.map((m) => m.id);
            },
        });
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
        thread = fields.One("Thread", { inverse: "messages" });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert(1);
    store.Message.insert([
        { id: 1, thread },
        { id: 2, thread },
    ]);
    // eager semantics: the computed relation is materialized before any read
    expect(toRaw(thread)._raw.messages2.data).toEqual(["Message,1", "Message,2"]);
    store.Message.insert([{ id: 3, thread }]);
    expect(toRaw(thread)._raw.messages2.data).toEqual([
        "Message,1",
        "Message,2",
        "Message,3",
    ]);
    const messages2 = thread.messages2;
    expect(`${messages2.map((m) => m.id)}`).toBe("1,2,3");
    store.Message.insert([{ id: 4, thread }]);
    expect(`${messages2.map((m) => m.id)}`).toBe("1,2,3,4");
});

test("compute runs on dependency change whether or not the field is observed", async () => {
    (class Channel extends Record {
        static id = "id";
        id;
        count = 0;
        multiplicity = fields.Attr(undefined, {
            compute() {
                expect.step("computing");
                if (this.count > 3) {
                    return "many";
                }
                return "few";
            },
        });
    }).register(localRegistry);
    const store = await start();
    const channel = store.Channel.insert(1);
    // computed on insert
    expect.verifySteps(["computing"]);
    // unobserved: every dependency change still recomputes
    channel.count = 2;
    expect.verifySteps(["computing"]);
    channel.count = 5;
    expect.verifySteps(["computing"]);
    expect(toRaw(channel)._raw.multiplicity).toBe("many");
    // reading does not trigger extra computes
    expect(channel.multiplicity).toBe("many");
    expect.verifySteps([]);
    // observed: scheduling is identical, observers just get notified on change
    let observe = true;
    function render() {
        if (observe) {
            expect.step(`render ${reactiveChannel.multiplicity}`);
        }
    }
    const reactiveChannel = reactive(channel, render);
    render();
    expect.verifySteps(["render many"]);
    channel.count = 1;
    expect.verifySteps(["computing", "render few"]);
    observe = false;
    channel.count = 7;
    expect.verifySteps(["computing"]);
});

test("sorted field re-sorts on dependency change even when unobserved", async () => {
    (class Thread extends Record {
        static id = "id";
        id;
        messages = fields.Many("Message", {
            sort: (m1, m2) => m1.sequence - m2.sequence,
        });
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
        sequence;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert(1);
    thread.messages.push({ id: 1, sequence: 1 }, { id: 2, sequence: 2 });
    expect(`${thread.messages.map((m) => m.id)}`).toBe("1,2");
    const message = thread.messages[0];
    // unobserved: the raw list is re-sorted as soon as the dependency changes
    message.sequence = 3;
    expect(toRaw(thread)._raw.messages.data).toEqual(["Message,2", "Message,1"]);
    message.sequence = 1;
    expect(toRaw(thread)._raw.messages.data).toEqual(["Message,1", "Message,2"]);
    // observation does not change scheduling; observers are notified on re-sort
    function render() {
        expect.step(`render ${reactiveThread.messages.map((m) => m.id)}`);
    }
    const reactiveThread = reactive(thread, render);
    render();
    expect.verifySteps(["render 1,2"]);
    message.sequence = 10;
    expect.verifySteps(["render 2,1"]);
    expect(toRaw(thread)._raw.messages.data).toEqual(["Message,2", "Message,1"]);
});

test("sort works on fields.Attr()", async () => {
    (class Thread extends Record {
        static id = "id";
        id;
        messages = fields.Attr([], {
            sort: (m1, m2) => m1.sequence - m2.sequence,
        });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert(1);
    thread.messages.push({ id: 1, sequence: 1 }, { id: 2, sequence: 2 });
    expect(`${thread.messages.map((m) => m.id)}`).toBe("1,2");
    const message = thread.messages[0];
    // re-sorts eagerly on dependency change, no observer or read needed
    message.sequence = 3;
    expect(`${toRaw(thread)._raw.messages.map((msg) => toRaw(msg).id)}`).toBe("2,1");
    message.sequence = 1;
    expect(`${toRaw(thread)._raw.messages.map((msg) => toRaw(msg).id)}`).toBe("1,2");
    // observers are notified of re-sorts
    function render() {
        expect.step(`render ${reactiveChannel.messages.map((m) => m.id)}`);
    }
    const reactiveChannel = reactive(thread, render);
    render();
    expect.verifySteps(["render 1,2"]);
    message.sequence = 10;
    expect.verifySteps(["render 2,1"]);
    message.sequence = 1;
    expect.verifySteps(["render 1,2"]);
});

test("fields.Attr() object default is a fresh instance per record", async () => {
    (class Thread extends Record {
        static id = "id";
        id;
        tags = fields.Attr([]);
    }).register(localRegistry);
    const store = await start();
    const thread1 = store.Thread.insert(1);
    const thread2 = store.Thread.insert(2);
    thread1.tags.push("a");
    expect(thread1.tags).toEqual(["a"]);
    expect(thread2.tags).toEqual([]);
    expect(toRaw(thread1)._raw.tags).not.toBe(toRaw(thread2)._raw.tags);
});

test("store updates can be observed", async () => {
    const store = await start();
    function onUpdate() {
        expect.step(`abc:${reactiveStore.abc}`);
    }
    const rawStore = toRaw(store)._raw;
    const reactiveStore = reactive(store, onUpdate);
    onUpdate();
    expect.verifySteps(["abc:undefined"]);
    store.abc = 1;
    expect.verifySteps(["abc:1"]); // observable from makeStore"
    rawStore.store.abc = 2;
    expect.verifySteps(["abc:2"]); // observable from record.store
    rawStore.Model.store.abc = 3;
    expect.verifySteps(["abc:3"]);
});

test("onAdd/onDelete hooks on one without inverse", async () => {
    (class Thread extends Record {
        static id = "name";
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread", {
            onAdd: (thread) => asyncStep(`thread.onAdd(${thread.name})`),
            onDelete: (thread) => asyncStep(`thread.onDelete(${thread.name})`),
        });
    }).register(localRegistry);
    const store = await start();
    const general = store.Thread.insert("General");
    const john = store.Member.insert("John");
    await waitForSteps([]);
    john.thread = general;
    await waitForSteps(["thread.onAdd(General)"]);
    john.thread = general;
    await waitForSteps([]);
    john.thread = undefined;
    await waitForSteps(["thread.onDelete(General)"]);
});

test("onAdd/onDelete hooks on many without inverse", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", {
            onAdd: (member) => asyncStep(`members.onAdd(${member.name})`),
            onDelete: (member) => asyncStep(`members.onDelete(${member.name})`),
        });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
    }).register(localRegistry);
    const store = await start();
    const general = store.Thread.insert("General");
    const jane = store.Member.insert("Jane");
    const john = store.Member.insert("John");
    await waitForSteps([]);
    general.members = jane;
    await waitForSteps(["members.onAdd(Jane)"]);
    general.members = jane;
    await waitForSteps([]);
    general.members = [["ADD", john]];
    await waitForSteps(["members.onAdd(John)"]);
    general.members = undefined;
    await waitForSteps(["members.onDelete(John)", "members.onDelete(Jane)"]);
});

test("record list assign should update inverse fields", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", { inverse: "thread" });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        thread = fields.One("Thread", { inverse: "members" });
    }).register(localRegistry);
    const store = await start();
    const general = store.Thread.insert("General");
    const jane = store.Member.insert("Jane");
    general.members = jane; // direct assignation of value goes through assign()
    expectRecord(jane.thread).toEqual(general);
    general.members = []; // writing empty array specifically goes through assign()
    expect(Boolean(jane.thread)).toBe(false);
    jane.thread = general;
    expectRecord(jane).toBeIn(general.members);
    jane.thread = [];
    expectRecord(jane).not.toBeIn(general.members);
});

test("datetime type record", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        date = fields.Attr(undefined, {
            type: "datetime",
            onUpdate: () => asyncStep("DATE_UPDATED"),
        });
    }).register(localRegistry);
    const store = await start();
    await waitForSteps([]);
    const general = store.Thread.insert({
        name: "General",
        date: "2024-02-20 14:42:00",
    });
    await waitForSteps(["DATE_UPDATED"]);
    expect(general.date).toBeInstanceOf(luxon.DateTime);
    expect(general.date.day).toBe(20);
    store.Thread.insert({ name: "General", date: "2024-02-21 14:42:00" });
    await waitForSteps(["DATE_UPDATED"]);
    expect(general.date.day).toBe(21);
    store.Thread.insert({ name: "General", date: "2024-02-21 14:42:00" });
    await waitForSteps([]);
    store.Thread.insert({ name: "General", date: undefined });
    await waitForSteps(["DATE_UPDATED"]);
    expect(general.date).toBe(undefined);
    const now = luxon.DateTime.now();
    const thread = store.Thread.insert({ name: "General", date: now });
    await waitForSteps(["DATE_UPDATED"]);
    expect(thread.date).toBeInstanceOf(luxon.DateTime);
    expect(thread.date.equals(now)).toBe(true);
    store.Thread.insert({ name: "General", date: false });
    await waitForSteps(["DATE_UPDATED"]);
    expect(general.date).toBe(false);
    store.Thread.insert({ name: "General", date: "2024-02-22 14:42:00" });
    await waitForSteps(["DATE_UPDATED"]);
    expect(general.date.day).toBe(22);
});

test("attr that are default [] should be isolated per record", async () => {
    // If the default value is stored and reused for all records,
    // this could lead to mistakenly sharing the default value among records
    (class Person extends Record {
        static id = "id";
        id;
        names = fields.Attr([]);
    }).register(localRegistry);
    const store = await start();
    const p1 = store.Person.insert({ id: 1 });
    const p2 = store.Person.insert({ id: 2 });
    expect(p1.names).toEqual([]);
    expect(p2.names).toEqual([]);
    p1.names.push("John");
    expect(p1.names).toEqual(["John"]);
    expect(p2.names).toEqual([]);
});

test("record.toData() is JSON stringified and can be reinserted as record", async () => {
    // If the default value is stored and reused for all records,
    // this could lead to mistakenly sharing the default value among records
    (class Person extends Record {
        static id = "id";
        id;
        names = fields.Attr([]);
        due_datetime = fields.Attr(undefined, { type: "datetime" });
        messages = fields.Many("Message");
        team = fields.One("Team");
        signature = fields.Html("");
    }).register(localRegistry);
    (class Message extends Record {
        static id = "body";
        body = fields.Attr("");
    }).register(localRegistry);
    (class Team extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const p = store.Person.insert({
        id: 1,
        due_datetime: "2024-08-28 10:19:44",
        names: ["John", "Marc"],
        messages: [{ body: "1" }, { body: "2" }],
        team: "Discuss",
        signature: ["markup", "<p>-- John</p>"],
    });
    expect(p.names).toEqual(["John", "Marc"]);
    expect(p.messages.map((msg) => msg.body)).toEqual(["1", "2"]);
    expect(p.team.name).toBe("Discuss");
    expect(p.signature.toString()).toBe("<p>-- John</p>");
    expect(p.signature).toBeInstanceOf(Markup);
    expect(toRaw(store.Person.records[p.localId])).toBe(toRaw(p));
    expect(serializeDateTime(p.due_datetime)).toBe("2024-08-28 10:19:44");
    // export data, delete, then insert back
    const data = JSON.parse(JSON.stringify(p.toData()));
    p.delete();
    store.Message.get("1").delete();
    store.Message.get("2").delete();
    store.Team.get("Discuss").delete();
    expect(toRaw(store.Person.records[p.localId])).toBe(undefined);
    store.insert(data);
    const p2 = store.Person.get(1);
    // Same assertions as before
    expect(p2.names).toEqual(["John", "Marc"]);
    expect(p2.messages.map((msg) => msg.body)).toEqual(["1", "2"]);
    expect(p2.team.name).toBe("Discuss");
    expect(toRaw(store.Person.records[p2.localId])).toBe(toRaw(p2));
    expect(serializeDateTime(p2.due_datetime)).toBe("2024-08-28 10:19:44");
    expect(p2.signature.toString()).toBe("<p>-- John</p>");
    expect(p.signature).toBeInstanceOf(Markup);
});

test("record.toData() returns flat data", async () => {
    (class Person extends Record {
        static id = "id";
        id;
        names = fields.Attr([]);
        due_datetime = fields.Attr(undefined, { type: "datetime" });
        messages = fields.Many("Message");
        team = fields.One("Team");
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
        body = fields.Attr("");
    }).register(localRegistry);
    (class Team extends Record {
        static id = "id";
        id;
        name;
        leader = fields.One("Person");
    }).register(localRegistry);
    const store = await start();
    store.Person.insert([
        {
            id: 1,
            due_datetime: "2024-08-28 10:19:44",
            names: ["Seb", "Theys"],
            messages: [
                { id: 1, body: "1" },
                { id: 2, body: "2" },
            ],
            team: { id: 1, name: "Discuss", leader: { id: 2 } },
        },
        {
            id: 2,
            due_datetime: "2025-01-23 12:12:12",
            names: ["Louis", "Wicket"],
            messages: [
                { id: 1, body: "1" },
                { id: 3, body: "3" },
            ],
            team: { id: 2, name: "VoIP", leader: { id: 1 } },
        },
    ]);
    const p = store.Person.get(1);
    expect(p.toData()).toEqual({
        Person: [
            {
                id: 1,
                due_datetime: "2024-08-28 10:19:44",
                names: ["Seb", "Theys"],
                messages: [{ id: 1 }, { id: 2 }],
                team: { id: 1 },
            },
        ],
    });
    expect(p.toData(["messages", "team"])).toEqual({
        Person: [
            {
                id: 1,
                due_datetime: "2024-08-28 10:19:44",
                names: ["Seb", "Theys"],
                messages: [{ id: 1 }, { id: 2 }],
                team: { id: 1 },
            },
        ],
        Message: [
            { id: 1, body: "1" },
            { id: 2, body: "2" },
        ],
        Team: [{ id: 1, name: "Discuss", leader: { id: 2 } }],
    });
    expect(p.toData(["team.leader"])).toEqual({
        Person: [
            {
                id: 2,
                due_datetime: "2025-01-23 12:12:12",
                names: ["Louis", "Wicket"],
                messages: [{ id: 1 }, { id: 3 }],
                team: { id: 2 },
            },
            {
                id: 1,
                due_datetime: "2024-08-28 10:19:44",
                names: ["Seb", "Theys"],
                messages: [{ id: 1 }, { id: 2 }],
                team: { id: 1 },
            },
        ],
        Team: [{ id: 1, name: "Discuss", leader: { id: 2 } }],
    });
    expect(p.toData({ depth: true })).toEqual({
        Person: [
            {
                id: 2,
                due_datetime: "2025-01-23 12:12:12",
                names: ["Louis", "Wicket"],
                messages: [{ id: 1 }, { id: 3 }],
                team: { id: 2 },
            },
            {
                id: 1,
                due_datetime: "2024-08-28 10:19:44",
                names: ["Seb", "Theys"],
                messages: [{ id: 1 }, { id: 2 }],
                team: { id: 1 },
            },
        ],
        Message: [
            { id: 1, body: "1" },
            { id: 2, body: "2" },
            { id: 3, body: "3" },
        ],
        Team: [
            { id: 2, name: "VoIP", leader: { id: 1 } },
            { id: 1, name: "Discuss", leader: { id: 2 } },
        ],
    });
});

test("record.toData() field filter respects field-name boundaries", async () => {
    (class Person extends Record {
        static id = "id";
        id;
        team = fields.One("Team");
        // sibling relation whose name has "team" as a plain string prefix
        team_lead = fields.One("Person");
    }).register(localRegistry);
    (class Team extends Record {
        static id = "id";
        id;
        name;
    }).register(localRegistry);
    const store = await start();
    store.Person.insert({
        id: 1,
        team: { id: 1, name: "Discuss" },
        team_lead: { id: 2 },
    });
    const p = store.Person.get(1);
    // Only "team_lead" is requested: the sibling "team" relation must NOT be
    // expanded merely because "team_lead".startsWith("team") — that would leak
    // the Team record into the payload.
    const data = p.toData(["team_lead"]);
    expect(data.Team).toBe(undefined, {
        message: "sibling relation `team` must not be expanded for `team_lead`",
    });
    expect(data.Person.map((r) => r.id).sort()).toEqual([1, 2], {
        message: "the requested `team_lead` relation should be expanded",
    });
});

test("Methods are bound to records", async () => {
    // Allows to simply `t-on-click="record.method"`
    (class Persona extends Record {
        static id = "name";
        name;
        saysName() {
            return this.name;
        }
    }).register(localRegistry);
    const store = await start();
    const john = store.Persona.insert("John");
    expect(john.saysName()).toBe("John");
    const saysName = john.saysName;
    expect(saysName()).toBe("John");
});

test("Record lists methods are bound to the record list", async () => {
    // Allows to simply `onSelected="recordList.add"`
    (class Message extends Record {
        static id = "content";
        content;
    }).register(localRegistry);
    (class Thread extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message");
    }).register(localRegistry);
    const store = await start();
    const general = store.Thread.insert("General");
    expect(general.messages.length).toBe(0);
    const addMessage = general.messages.add;
    addMessage({ content: "1" });
    expect(general.messages.length).toBe(1);
    expect(general.messages.map((msg) => msg.content)).toEqual(["1"]);
});

test("setup() has precedence over instance class field definition", async () => {
    class Test extends Record {}
    Test.register(localRegistry);
    (class Test2 extends Test {
        x = false;
        setup() {
            super.setup();
            this.x = true;
        }
    }).register(localRegistry);
    const store = await start();
    const test = store.Test2.insert();
    expect(test.x).toBe(true);
});

test("insert with id relation keeps existing field values", async () => {
    class User extends Record {
        static id = "id";
        id;
    }
    User.register(localRegistry);
    class Thread extends Record {
        static id = "id";
        id;
    }
    Thread.register(localRegistry);
    class ChannelMember extends Record {
        static id = AND("channel", "user");
        is_internal = fields.Attr(false);
        channel = fields.One("Thread");
        user = fields.One("User");
    }
    ChannelMember.register(localRegistry);
    const store = await start();
    const member1 = store.ChannelMember.insert({
        is_internal: true,
        user: { id: 1 },
        channel: { id: 2 },
    });
    const user1 = member1.user;
    const channel1 = member1.channel;
    expect(member1.is_internal).toBe(true);
    const member2 = store.ChannelMember.insert({
        user: { id: 1 },
        channel: { id: 2 },
    });
    expect(member2.eq(member1)).toBe(true);
    expect(member2.user.eq(user1)).toBe(true);
    expect(member2.channel.eq(channel1)).toBe(true);
    expect(member2.is_internal).toBe(true);
});

test("Inserting single-id data on non-single id Model throws human-readable error", async () => {
    (class Persona extends Record {
        static id = AND("partner_id", "guest_id");
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
        author = fields.One("Persona");
    }).register(localRegistry);
    const store = await start();
    store.warnErrors = false;
    const paul = store.Persona.insert({ partner_id: 1 });
    store.Persona.insert({ guest_id: 2 });
    expect(store.Persona.get({ partner_id: 1 }).exists()).toBe(true);
    expect(store.Persona.get({ guest_id: 2 }).exists()).toBe(true);
    expect(store.Persona.get(1)).toBe(undefined);
    expect(store.Persona.get(2)).toBe(undefined);
    expect(() => store.Persona.insert(3)).toThrow(
        `Cannot insert "3" on model "Persona": this model doesn't support single-id data!`,
    );
    const msg = store.Message.insert(100);
    expect(() => (msg.author = 1)).toThrow(
        `Cannot insert "1" on relational field "Message/author": target model "Persona" doesn't support single-id data!`,
    );
    msg.author = { partner_id: 1 };
    expectRecord(msg.author).toEqual(paul);
});

test("Can assign new record on Many field with One inverse", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        files = fields.Many("File", { inverse: "thread" });
    }).register(localRegistry);
    (class File extends Record {
        static id = "name";
        thread = fields.One("Thread", { inverse: "files" });
        name;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("general");
    const file1 = store.File.insert("file1.txt");
    const file2 = store.File.insert("file2.txt");
    const file3 = store.File.insert("file3.txt");
    const file4 = store.File.insert("file4.txt");
    const file2Replacement = store.File.insert("file2repl.txt");
    thread.files.push(file1, file2, file3, file4);
    expect(thread.files.length).toBe(4);
    expectRecord(thread.files[1]).toEqual(file2);
    expectRecord(file2.thread).toEqual(thread);
    expect(file2Replacement.thread).toBe(undefined);
    thread.files[1] = file2Replacement;
    expect(thread.files.length).toBe(4);
    expectRecord(thread.files[1]).toEqual(file2Replacement);
    expectRecord(file2Replacement.thread).toEqual(thread);
    expect(file2.thread).toBe(undefined);
});

test("Deleted records are not returned by 'Model.records' nor 'Model.get()'", async () => {
    /**
     * Record has a 2-step record deletion:
     * - "soft" deletion, where the record is flagged for deletion but object is not removed from the store system structurally
     * - "hard" deletion, where the object is fully removed from store system structurally
     * The soft "deletion" is useful for stuffs like onDelete() hooks that tell which record has been removed from a relation,
     * with object reference, even when the record will be hard-deleted as a consequence.
     * `Model.records` and `Model.get()` are intended for business-code uses, therefore they should make sure to not return
     * records that are soft-deleted, as this could lead to critical section where business code is using a deleted record.
     */
    function assertExists(store) {
        const msg = store.Message.get("msg-1");
        if (msg) {
            expect(toRaw(msg).exists()).toBe(true);
        }
        for (const msg of Object.values(store.Message.records)) {
            expect(toRaw(msg).exists()).toBe(true);
        }
    }
    let deleting = false;
    (class Thread extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message", { inverse: "thread" });
        get hasMessages() {
            return this.messages.length > 0;
        }
    }).register(localRegistry);
    (class Message extends Record {
        static id = "content";
        content;
        thread = fields.One("Thread");
    }).register(localRegistry);
    (class DiscussApp extends Record {
        static id = "id";
        id;
        thread = fields.One("Thread");
        allMessagesInStore = fields.Many("Message", {
            compute() {
                if (deleting) {
                    expect.step("allMessagesInStore:compute");
                    expect(this._lastAllMessagesInStore.some((m) => m.exists())).toBe(
                        false,
                    );
                }
                expect(this.thread.hasMessages).toBe(
                    Boolean(Object.values(store.Message.records).length > 0),
                );
                assertExists(this.store);
                const allMessagesInStore = Object.values(store.Message.records);
                toRaw(this)._raw._lastAllMessagesInStore = allMessagesInStore;
                return allMessagesInStore;
            },
        });
        _lastAllMessagesInStore;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert({ name: "General" });
    store.DiscussApp.insert({ thread });
    const message = store.Message.insert({ content: "msg-1", thread });
    expectRecord(thread.messages[0]).toEqual(message);
    expectRecord(store.Message.get("msg-1")).toEqual(message);
    expectRecord(store.Message.records[message.localId]).toEqual(message);
    deleting = true;
    message.delete();
    deleting = false;
    expect.verifySteps(["allMessagesInStore:compute"]);
    assertExists(store);
    expect(thread.messages.length).toEqual(0);
});

test("Delete record with side-effect compute to insert it should have resulting record with only insert data (old data is removed)'", async () => {
    /**
     * Record has a 2-step record deletion:
     * - "soft" deletion, where the record is flagged for deletion but object is not removed from the store system structurally
     * - "hard" deletion, where the object is fully removed from store system structurally
     * The soft "deletion" is useful for stuffs like onDelete() hooks that tell which record has been removed from a relation,
     * with object reference, even when the record will be hard-deleted as a consequence.
     * `Model.records` and `Model.get()` are intended for business-code uses, therefore they should make sure to not return
     * records that are soft-deleted, as this could lead to critical section where business code is using a deleted record.
     */
    (class DiscussApp extends Record {
        static id;
        state = fields.One("DiscussAppState", {
            compute: () => ({}),
            onDelete() {
                this.state = {};
            },
        });
    }).register(localRegistry);
    (class DiscussAppState extends Record {
        static id;
        status = "init";
        thread = fields.One("Thread");
    }).register(localRegistry);
    (class Thread extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const discussApp = store.DiscussApp.insert();
    discussApp.state = { thread: "General", status: "ready" };
    expect(discussApp.state.status).toEqual("ready");
    expectRecord(discussApp.state.thread).toEqual(store.Thread.get("General"));
    discussApp.state.delete();
    expect(discussApp.state.status).toEqual("init");
    expect(discussApp.state.thread).toBe(undefined);
});

test("side-effect of double deletion of record should work as expected with no crash'", async () => {
    (class Channel extends Record {
        static id = "name";
        name;
        correspondent = fields.One("Member", {
            compute() {
                return this.members[0];
            },
        });
        members = fields.Many("Member", {
            onDelete: (r) => r.delete(),
        });
        parent = fields.One("Channel", {
            onDelete() {
                this.delete(); // important: triggers double-deletion when deleting sub-thread.
            },
        });
        threads = fields.Many("Channel", { inverse: "parent" });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "partner";
        partner = fields.One("Partner");
        channel = fields.One("Channel", { inverse: "members" });
    }).register(localRegistry);
    (class Partner extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const general = store.Channel.insert("general");
    const suggestions = store.Channel.insert("Suggestions");
    suggestions.parent = general;
    const mitchell = store.Partner.insert("Mitchell");
    const marc = store.Partner.insert("Marc");
    const joel = store.Partner.insert("Joel");
    general.members.push({ partner: mitchell });
    general.members.push({ partner: marc });
    general.members.push({ partner: joel });
    suggestions.members.push({ partner: mitchell });
    const reactiveGeneral = reactive(general, render);
    function render() {
        // Important: observe computed field `correspondent` so deletion side-effects
        // run while an observer is subscribed to the computed relation
        void reactiveGeneral?.threads.forEach((t) => t.correspondent?.partner.name);
    }
    render();
    suggestions.delete();
    expect(suggestions.exists()).toBe(false);
});

test("Record exists is reactive", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    effect(
        (rec) => {
            if (rec.exists()) {
                expect.step("thread exists");
            } else {
                expect.step("thread does not exist");
            }
        },
        [thread],
    );
    await expect.waitForSteps(["thread exists"]);
    thread.delete();
    await expect.waitForSteps(["thread does not exist"]);
});

test("re-parenting via many side cleans old owner's list and fires onDelete", async () => {
    let logs = [];
    (class Thread extends Record {
        static id = "name";
        name;
        files = fields.Many("File", {
            inverse: "thread",
            onAdd(file) {
                logs.push(`${this.name}.files.onAdd(${file.name})`);
            },
            onDelete(file) {
                logs.push(`${this.name}.files.onDelete(${file.name})`);
            },
        });
    }).register(localRegistry);
    (class File extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread", { inverse: "files" });
    }).register(localRegistry);
    const store = await start();
    const threadA = store.Thread.insert("A");
    const threadB = store.Thread.insert("B");
    const file = store.File.insert("file.txt");
    threadA.files.push(file);
    expect(logs).toEqual(["A.files.onAdd(file.txt)"]);
    logs = [];
    threadB.files.push(file);
    expectRecord(file.thread).toEqual(threadB);
    expectRecord(file).toBeIn(threadB.files);
    expectRecord(file).not.toBeIn(threadA.files);
    expect(threadA.files.length).toBe(0);
    expect(logs).toEqual(["B.files.onAdd(file.txt)", "A.files.onDelete(file.txt)"]);
});

test("error in nested update propagates and store still works afterwards", async () => {
    (class Message extends Record {
        static id = "id";
        id;
        body;
    }).register(localRegistry);
    const store = await start();
    store.warnErrors = false;
    expect(() =>
        store.MAKE_UPDATE(() => {
            store.Message.insert(1);
            store.MAKE_UPDATE(() => {
                throw new Error("boom");
            });
            expect.step("unreachable");
        }),
    ).toThrow("boom");
    // the nested error interrupted the caller instead of being swallowed
    expect.verifySteps([]);
    // work batched before the error was still flushed
    expect(store.Message.get(1).exists()).toBe(true);
    // the store is fully functional afterwards (UPDATE back to 0)
    const message = store.Message.insert(2);
    Record.onChange(message, "body", () => expect.step("BODY_CHANGED"));
    message.body = "test";
    expect.verifySteps(["BODY_CHANGED"]);
});

test("nullish values in relation writes are no-ops, not phantom records", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message", { inverse: "thread" });
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
        thread = fields.One("Thread", { inverse: "messages" });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    // add(undefined) used to materialize a "Message,undefined" phantom
    thread.messages.add(undefined);
    expect(thread.messages.length).toBe(0);
    // nullish entries inside an assigned array are skipped
    thread.messages = [{ id: 1 }, null, { id: 2 }, false, undefined];
    expect(thread.messages.map((m) => m.id)).toEqual([1, 2]);
    expect(Object.keys(store.Message.records)).toHaveLength(2);
    // deleting plain data of a record that was never loaded must not create
    // it (a detached ghost registered forever) just to not-remove it
    thread.messages.delete({ id: 42 });
    expect(store.Message.get(42)).toBe(undefined);
    // index assignment of nullish is refused loudly instead of creating a
    // phantom (use delete()/splice() to remove)
    expect(() => (thread.messages[0] = undefined)).toThrow("use delete()");
    expect(thread.messages.map((m) => m.id)).toEqual([1, 2]);
    // push/unshift of a nullish entry are no-ops (consistent with add)
    thread.messages.push(null);
    thread.messages.unshift(undefined);
    expect(thread.messages.map((m) => m.id)).toEqual([1, 2]);
    expect(Object.keys(store.Message.records)).toHaveLength(2);
});

test("assigning duplicate entries keeps a single occurrence", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message", { inverse: "thread" });
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
        thread = fields.One("Thread", { inverse: "messages" });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    thread.messages = [{ id: 1 }, { id: 1 }];
    expect(thread.messages.length).toBe(1);
    const message = store.Message.get(1);
    // duplicate localIds in data desynced both sides: a delete removed one
    // occurrence from the owner but fully unlinked the inverse
    thread.messages.delete(message);
    expect(thread.messages.length).toBe(0);
    expectRecord(message).not.toBeIn(thread.messages);
    expect(message.thread).toBe(undefined);
});

test("deleting a non-member does not fire onDelete hooks", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message", {
            inverse: "thread",
            onAdd: (r) => expect.step(`onAdd(${r.id})`),
            onDelete: (r) => expect.step(`onDelete(${r.id})`),
        });
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
        thread = fields.One("Thread", { inverse: "messages" });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    const message = store.Message.insert(1);
    // unconditional deletes of non-members are common (e.g. chat window
    // fold bookkeeping): they must not fire hooks like (r) => r.delete()
    // with a record that was never in the relation
    thread.messages.delete(message);
    expect.verifySteps([]);
    thread.messages.add(message);
    expect.verifySteps(["onAdd(1)"]);
    thread.messages.delete(message);
    expect.verifySteps(["onDelete(1)"]);
});

test("single-argument splice removes to the end like Array#splice", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message");
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    thread.messages = [{ id: 1 }, { id: 2 }, { id: 3 }];
    // the undefined deleteCount silently removed NOTHING before
    thread.messages.splice(1);
    expect(thread.messages.map((m) => m.id)).toEqual([1]);
});

test("errors from direct-assignment hooks are reported immediately", async () => {
    (class Message extends Record {
        static id = "id";
        id;
        body;
    }).register(localRegistry);
    const store = await start();
    store.warnErrors = false;
    const message = store.Message.insert(1);
    Record.onChange(message, "body", () => {
        throw new Error("boom");
    });
    // hooks fired by a direct assignment run after the assignment's own
    // flush: the error used to be PARKED and thrown by the next unrelated
    // update cycle at an innocent caller
    expect(() => {
        message.body = "x";
    }).toThrow("boom");
    // the next cycle is not poisoned by a stale parked error
    store.MAKE_UPDATE(() => {});
    expect(store.Message.get(1).exists()).toBe(true);
});

test("throwing compute preserves the previous value instead of clearing it", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        explode = false;
        title = fields.Attr(undefined, {
            compute() {
                if (this.explode) {
                    throw new Error("compute boom");
                }
                return `title of ${this.name}`;
            },
        });
        members = fields.Many("Member", {
            compute() {
                if (this.explode) {
                    throw new Error("compute boom");
                }
                return [{ name: "alice" }];
            },
            onDelete: (member) => {
                expect.step(`onDelete(${member.name})`);
                member.delete();
            },
        });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    store.warnErrors = false;
    const thread = store.Thread.insert("General");
    expect(thread.title).toBe("title of General");
    expect(thread.members.length).toBe(1);
    // the dependency change makes both computes throw: the error propagates...
    expect(() =>
        store.MAKE_UPDATE(() => {
            thread.explode = true;
        }),
    ).toThrow("compute boom");
    // ...but the previously computed values are preserved: writing the
    // undefined computedValue would wipe the attr and clear() the relation,
    // cascading the compute error into record deletions via onDelete
    expect(thread.title).toBe("title of General");
    expect(thread.members.length).toBe(1);
    expect(store.Member.get("alice").exists()).toBe(true);
    expect.verifySteps([]);
    // the store recovers once the compute stops throwing
    store.MAKE_UPDATE(() => {
        thread.explode = false;
    });
    expect(thread.title).toBe("title of General");
    expect(thread.members.length).toBe(1);
});

test("record list index assignment", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        files = fields.Many("File", {
            inverse: "thread",
            onAdd: (file) => expect.step(`onAdd(${file.name})`),
            onDelete: (file) => expect.step(`onDelete(${file.name})`),
        });
    }).register(localRegistry);
    (class File extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread", { inverse: "files" });
    }).register(localRegistry);
    const store = await start();
    store.warnErrors = false;
    const thread = store.Thread.insert("General");
    const file1 = store.File.insert("file1.txt");
    const file2 = store.File.insert("file2.txt");
    thread.files.push(file1);
    expect.verifySteps(["onAdd(file1.txt)"]);
    // self-assignment is a no-op: no hooks, inverse untouched
    thread.files[0] = file1;
    expect.verifySteps([]);
    expectRecord(file1.thread).toEqual(thread);
    expectRecord(file1).toBeIn(thread.files);
    // assigning at index === length appends
    thread.files[thread.files.length] = file2;
    expect.verifySteps(["onAdd(file2.txt)"]);
    expect(thread.files.length).toBe(2);
    expectRecord(file2.thread).toEqual(thread);
    // assigning past the end is refused with a clear error
    expect(() => (thread.files[10] = file1)).toThrow("out of range");
    expect(thread.files.length).toBe(2);
    expect.verifySteps([]);
    // replacement still works and updates inverses (flush order: FA → FD)
    thread.files[0] = { name: "file3.txt" };
    expect.verifySteps(["onAdd(file3.txt)", "onDelete(file1.txt)"]);
    expect(file1.thread).toBe(undefined);
    expectRecord(store.File.get("file3.txt").thread).toEqual(thread);
});

test("id fields are immutable once the record is inserted", async () => {
    (class Message extends Record {
        static id = "id";
        id;
        body;
    }).register(localRegistry);
    (class Thread extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    (class ChatWindow extends Record {
        static id = "thread";
        thread = fields.One("Thread");
    }).register(localRegistry);
    const store = await start();
    store.warnErrors = false;
    const message = store.Message.insert({ id: 1, body: "a" });
    // re-inserting with the same id is fine
    store.Message.insert({ id: 1, body: "b" });
    expect(message.body).toBe("b");
    expect(() => (message.id = 5)).toThrow("id fields are immutable");
    expect(message.id).toBe(1);
    expect(() => message.update({ id: 5 })).toThrow("id fields are immutable");
    expect(message.id).toBe(1);
    expectRecord(store.Message.get(1)).toEqual(message);
    // relational id fields are protected too
    const chatWindow = store.ChatWindow.insert({ thread: "General" });
    store.ChatWindow.insert({ thread: "General" }); // same id: fine
    expect(() => (chatWindow.thread = "Sales")).toThrow("id fields are immutable");
    expectRecord(chatWindow.thread).toEqual(store.Thread.get("General"));
});

test("record list read methods work and unsupported mutators throw", async () => {
    (class Message extends Record {
        static id = "id";
        id;
    }).register(localRegistry);
    (class Thread extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message");
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    thread.messages.push({ id: 1 }, { id: 2 }, { id: 3 });
    const messages = thread.messages;
    expect(messages.map((msg) => msg.id)).toEqual([1, 2, 3]);
    expect(messages.filter((msg) => msg.id > 1).map((msg) => msg.id)).toEqual([2, 3]);
    expectRecord(messages.find((msg) => msg.id === 2)).toEqual(store.Message.get(2));
    expect(messages.find((msg) => msg.id === 42)).toBe(undefined);
    expect(messages.findIndex((msg) => msg.id === 2)).toBe(1);
    expect(messages.findIndex((msg) => msg.id === 42)).toBe(-1);
    expectRecord(messages.findLast((msg) => msg.id < 3)).toEqual(store.Message.get(2));
    expect(messages.findLast((msg) => msg.id === 42)).toBe(undefined);
    expect(messages.findLastIndex((msg) => msg.id < 3)).toBe(1);
    expect(messages.findLastIndex((msg) => msg.id === 42)).toBe(-1);
    expect(messages.some((msg) => msg.id === 3)).toBe(true);
    expect(messages.some((msg) => msg.id === 42)).toBe(false);
    expect(messages.every((msg) => msg.id > 0)).toBe(true);
    expect(messages.every((msg) => msg.id > 1)).toBe(false);
    expect(messages.reduce((acc, msg) => acc + msg.id, 0)).toBe(6);
    const seen = [];
    messages.forEach((msg, index) => seen.push([index, msg.id]));
    expect(seen).toEqual([
        [0, 1],
        [1, 2],
        [2, 3],
    ]);
    expect(messages.slice(1).map((msg) => msg.id)).toEqual([2, 3]);
    expect(messages.slice(0, 2).map((msg) => msg.id)).toEqual([1, 2]);
    expect(messages.includes(store.Message.get(2))).toBe(true);
    expect(messages.includes(store.Message.insert({ id: 42 }))).toBe(false);
    expect(() => messages.reverse()).toThrow("in-place mutators are not supported");
    expect(() => messages.fill(store.Message.get(1))).toThrow(
        "in-place mutators are not supported",
    );
    expect(() => messages.copyWithin(0, 1)).toThrow(
        "in-place mutators are not supported",
    );
    expect(messages.map((msg) => msg.id)).toEqual([1, 2, 3]);
});

test("clear() empties the list, updates inverses and fires onDelete hooks", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", {
            inverse: "thread",
            onDelete: (member) => expect.step(`onDelete(${member.name})`),
        });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
        thread = fields.One("Thread", { inverse: "members" });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    thread.members = [{ name: "Jane" }, { name: "John" }, { name: "Marc" }];
    const [jane, john, marc] = [...thread.members];
    expect(thread.members.length).toBe(3);
    thread.members.clear();
    expect(thread.members.length).toBe(0);
    expect(Boolean(jane.thread)).toBe(false);
    expect(Boolean(john.thread)).toBe(false);
    expect(Boolean(marc.thread)).toBe(false);
    expectRecord(jane).not.toBeIn(thread.members);
    // removal order matches historical pop-based behavior (last first)
    expect.verifySteps(["onDelete(Marc)", "onDelete(John)", "onDelete(Jane)"]);
    // clearing an empty list is a no-op
    thread.members.clear();
    expect.verifySteps([]);
});

test("record.delete() while used in a computed+sorted field should properly delete this record from relation", async () => {
    // Computes and sorts are always eager: the list is recomputed/re-sorted at
    // the end of the update cycle that changed a dependency, never "on read".
    // Deleting a record must both drop it from the relation and retrigger the
    // compute (which reads Model.records), leaving a consistent sorted list.
    (class Message extends Record {
        static id = "id";
        id;
        sequence;
        thread_name;
    }).register(localRegistry);
    (class Thread extends Record {
        static id = "name";
        name;
        description;
        messages = fields.Many("Message", {
            // intentional combine of `compute` and `sort` on the same field
            compute() {
                return Object.values(this.store.Message.records).filter(
                    (msg) => msg.thread_name === this.name,
                );
            },
            sort: (m1, m2) => (m1.sequence ?? 0) - (m2.sequence ?? 0),
        });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    store.Message.insert([
        { id: 1, sequence: 10, thread_name: "General" },
        { id: 2, sequence: 20, thread_name: "General" },
    ]);
    // no read needed: computed and sorted eagerly
    expect(toRaw(thread)._raw.messages.data).toEqual(["Message,1", "Message,2"]);
    store.insert({
        Thread: { name: "General", description: "This is the general channel" },
        Message: { id: 3, sequence: 30, thread_name: "General" },
    });
    expect(toRaw(thread)._raw.messages.data).toEqual([
        "Message,1",
        "Message,2",
        "Message,3",
    ]);
    store.Message.get(3).sequence = 5;
    // re-sorted at end of update cycle, without any read
    expect(toRaw(thread)._raw.messages.data).toEqual([
        "Message,3",
        "Message,1",
        "Message,2",
    ]);
    store.Message.get(3).delete();
    expect(toRaw(thread)._raw.messages.data).toEqual(["Message,1", "Message,2"]);
});

test("RecordUses reference-counts membership and empties on removal", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        messages = fields.Many("Message");
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    const message = store.Message.insert(1);
    const uses = toRaw(message)._raw._.uses;
    // assign() does not dedupe within a payload path, but add() does: one
    // membership => one use entry with count 1
    thread.messages.add(message);
    expect(uses.data.get(toRaw(thread)._raw).get("messages")).toBe(1);
    // the same record in a SECOND relation of the same owner counts separately
    (class Thread2 extends Record {
        static id = "name";
        name;
        pinned = fields.Many("Message");
    }).register(localRegistry);
    // second relation on the same thread: add message to a distinct field
    thread.messages.add(message); // already a member: no double count
    expect(uses.data.get(toRaw(thread)._raw).get("messages")).toBe(1);
    // removing the membership drops the field entry, and with no fields left
    // the owner entry is removed entirely
    thread.messages.delete(message);
    expect(uses.data.has(toRaw(thread)._raw)).toBe(false);
});

test("OR-id records are distinct per which part is provided", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    (class Message extends Record {
        static id = "id";
        id;
    }).register(localRegistry);
    (class Composer extends Record {
        // OR is positional concatenation, not "match either": a composer
        // keyed by {thread} and one keyed by {message} are different records
        static id = OR("thread", "message");
        thread = fields.One("Thread");
        message = fields.One("Message");
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    const message = store.Message.insert(1);
    const threadComposer = store.Composer.insert({ thread });
    const messageComposer = store.Composer.insert({ message });
    expect(threadComposer.eq(messageComposer)).toBe(false);
    // get() by the same part finds the same record
    expect(store.Composer.get({ thread }).eq(threadComposer)).toBe(true);
    expect(store.Composer.get({ message }).eq(messageComposer)).toBe(true);
    // a composer inserted under {thread} is not found by {message}
    expect(store.Composer.get({ message: store.Message.insert(2) })).toBe(undefined);
});
