import { defineMailModels, start as start2 } from "@mail/../tests/mail_test_helpers";
import { makeStore, Record, Store } from "@mail/core/common/record";
import { fields } from "@mail/model/misc";
import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
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

test("one flush runs onAdd, then onDelete, then onUpdate, then onChange", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", {
            onAdd: (member) => expect.step(`onAdd(${member.name})`),
            onDelete: (member) => expect.step(`onDelete(${member.name})`),
        });
        topic = fields.Attr("", {
            onUpdate() {
                expect.step(`onUpdate(${this.topic})`);
            },
        });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    thread.members = [{ name: "alice" }];
    Record.onChange(thread, "topic", () => expect.step("onChange(topic)"));
    expect.verifySteps(["onAdd(alice)"]);

    store.MAKE_UPDATE(() => {
        thread.members = [{ name: "bob" }];
        thread.topic = "weather";
    });
    expect.verifySteps([
        "onAdd(bob)",
        "onDelete(alice)",
        "onUpdate(weather)",
        "onChange(topic)",
    ]);
});

test("a nested update defers its callbacks to the outermost one", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        topic = fields.Attr("", {
            onUpdate() {
                expect.step(`onUpdate(${this.topic})`);
            },
        });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");

    store.MAKE_UPDATE(() => {
        store.MAKE_UPDATE(() => {
            thread.topic = "inner";
        });
        expect.step("after inner update returned");
    });
    expect.verifySteps(["after inner update returned", "onUpdate(inner)"]);
});

test("work a hook queues is flushed by the same update", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        first = fields.Attr("", {
            onUpdate() {
                expect.step(`first=${this.first}`);
                if (this.first === "go") {
                    this.second = "queued by first";
                }
            },
        });
        second = fields.Attr("", {
            onUpdate() {
                expect.step(`second=${this.second}`);
            },
        });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");

    store.MAKE_UPDATE(() => {
        thread.first = "go";
    });
    expect(thread.second).toBe("queued by first");
    expect.verifySteps(["first=go", "second=queued by first"]);
});

test("a flush that never converges is reported instead of hanging", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        ping = fields.Attr(0, {
            onUpdate() {
                this.pong = this.ping + 1;
            },
        });
        pong = fields.Attr(0, {
            onUpdate() {
                this.ping = this.pong + 1;
            },
        });
    }).register(localRegistry);
    const store = await start();
    store.logErrors = false;
    const thread = store.Thread.insert("General");
    expect(() =>
        store.MAKE_UPDATE(() => {
            thread.ping = 1;
        }),
    ).toThrow("Store flush did not converge (1000 iterations)");
});

test("the first error is thrown and the next update starts clean", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        topic = fields.Attr("");
        label = fields.Attr("");
    }).register(localRegistry);
    const store = await start();
    store.logErrors = false;
    const thread = store.Thread.insert("General");
    Record.onChange(thread, "topic", () => {
        throw new Error("first boom");
    });
    Record.onChange(thread, "topic", () => {
        throw new Error("second boom");
    });
    expect(() =>
        store.MAKE_UPDATE(() => {
            thread.topic = "x";
        }),
    ).toThrow("first boom");

    Record.onChange(thread, "label", () => expect.step("still working"));
    store.MAKE_UPDATE(() => {
        thread.label = "after the error";
    });
    expect.verifySteps(["still working"]);
});

test("two fields written in one update each run once, in the order queued", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        topic = fields.Attr("", {
            onUpdate() {
                expect.step(`topic=${this.topic}`);
            },
        });
        label = fields.Attr("", {
            onUpdate() {
                expect.step(`label=${this.label}`);
            },
        });
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");

    store.MAKE_UPDATE(() => {
        thread.topic = "first";
        thread.label = "L";
        thread.topic = "second";
    });
    expect(thread.topic).toBe("second");
    expect.verifySteps(["topic=second", "label=L"]);
});

test("the same record added twice in one update runs onAdd once", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", {
            onAdd: (member) => expect.step(`onAdd(${member.name})`),
        });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");
    const alice = store.Member.insert("alice");

    store.MAKE_UPDATE(() => {
        thread.members.add(alice);
        thread.members.add(alice);
    });
    expect(thread.members.length).toBe(1);
    expect.verifySteps(["onAdd(alice)"]);
});

test("a sorted relation is in order after several adds in one update", async () => {
    (class Thread extends Record {
        static id = "name";
        name;
        members = fields.Many("Member", {
            sort: (m1, m2) => m1.name.localeCompare(m2.name),
        });
    }).register(localRegistry);
    (class Member extends Record {
        static id = "name";
        name;
    }).register(localRegistry);
    const store = await start();
    const thread = store.Thread.insert("General");

    store.MAKE_UPDATE(() => {
        thread.members.add(store.Member.insert("charlie"));
        thread.members.add(store.Member.insert("alice"));
        thread.members.add(store.Member.insert("bob"));
    });
    expect(thread.members.map((member) => member.name)).toEqual([
        "alice",
        "bob",
        "charlie",
    ]);
});
