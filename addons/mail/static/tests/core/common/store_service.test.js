import {
    defineMailModels,
    onRpcBefore,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { Message } from "@mail/core/common/message_model";
import { expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import {
    asyncStep,
    Command,
    getService,
    patchWithCleanup,
    serverState,
    waitForSteps,
} from "@web/../tests/web_test_helpers";

defineMailModels();

test("store.insert can delete record", async () => {
    await start();
    const store = getService("mail.store");
    store.insert({ "mail.message": [{ id: 1 }] });
    expect(store["mail.message"].get({ id: 1 })?.id).toBe(1);
    store.insert({ "mail.message": [{ id: 1, _DELETE: true }] });
    expect(store["mail.message"].get({ id: 1 })?.id).toBe(undefined);
});

test("store.insert deletes record without creating it", async () => {
    patchWithCleanup(Message, {
        new() {
            const message = super.new(...arguments);
            asyncStep(`new-${message.id}`);
            return message;
        },
    });
    await start();
    const store = getService("mail.store");
    store.insert({ "mail.message": [{ id: 1, _DELETE: true }] });
    await waitForSteps([]);
    expect(store["mail.message"].get({ id: 1 })?.id).toBe(undefined);
    store.insert({ "mail.message": [{ id: 2 }] });
    await waitForSteps(["new-2"]);
});

test("store.insert deletes record after relation created it", async () => {
    patchWithCleanup(Message, {
        new() {
            const message = super.new(...arguments);
            asyncStep(`new-${message.id}`);
            return message;
        },
    });
    await start();
    const store = getService("mail.store");
    store.insert({
        "mail.message": [{ id: 1, _DELETE: true }],
        // they key coverage of the test is to have the relation listed after the delete
        "mail.link.preview": [{ id: 1 }],
        "mail.message.link.preview": [{ id: 1, link_preview_id: 1, message_id: 1 }],
    });
    await waitForSteps(["new-1"]);
    expect(store["mail.message"].get({ id: 1 })?.id).toBe(undefined);
});

test("malformed fetched data does not block later fetches", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John" });
    await start();
    const store = getService("mail.store");
    patchWithCleanup(console, {
        error: () => asyncStep("console.error"),
    });
    onRpcBefore("/mail/data", (args) => {
        const isMalformedTarget = args.fetch_params.some(
            (param) =>
                Array.isArray(param) &&
                param[0] === "mail.thread" &&
                param[1]?.thread_id === partnerId,
        );
        if (isMalformedTarget) {
            // single-id data on a compound-id model ("mail.thread" resolves to
            // Thread, whose id is AND(model, id)): Store.insert() throws on it
            return { "mail.thread": [1] };
        }
    });
    const lastDataRequestId = store.DataResponse._lastId;
    let error;
    try {
        await store.fetchStoreData("mail.thread", {
            thread_model: "res.partner",
            thread_id: partnerId,
            request_list: [],
        });
    } catch (e) {
        error = e;
    }
    expect(Boolean(error)).toBe(true);
    await waitForSteps(["console.error"]);
    // the failed batch must not leak its data requests
    expect(
        Object.values(store.DataResponse.records).filter(
            (dataRequest) => dataRequest.id > lastDataRequestId,
        ),
    ).toHaveLength(0);
    // and the fetch machinery must remain usable for later requests
    await store.fetchStoreData("mail.thread", {
        thread_model: "res.partner",
        thread_id: serverState.partnerId,
        request_list: [],
    });
    expect(
        Boolean(store.Thread.get({ model: "res.partner", id: serverState.partnerId })),
    ).toBe(true);
});

test("posting on one thread does not block posting on other threads", async () => {
    const pyEnv = await startServer();
    const [channelId1, channelId2] = pyEnv["discuss.channel"].create([
        {
            channel_member_ids: [Command.create({ partner_id: serverState.partnerId })],
            name: "channel1",
        },
        {
            channel_member_ids: [Command.create({ partner_id: serverState.partnerId })],
            name: "channel2",
        },
    ]);
    const firstPostDeferred = new Deferred();
    onRpcBefore("/mail/message/post", async (args) => {
        if (args.thread_id === channelId1) {
            await firstPostDeferred;
        }
    });
    await start();
    const store = getService("mail.store");
    const thread1 = await store.Thread.getOrFetch({
        model: "discuss.channel",
        id: channelId1,
    });
    const thread2 = await store.Thread.getOrFetch({
        model: "discuss.channel",
        id: channelId2,
    });
    const post1 = thread1.post("blocked post");
    // with a single global mutex this await would never resolve as long as the
    // first post is pending
    const message2 = await thread2.post("fast post");
    expect(String(message2.body)).toInclude("fast post");
    expect(thread1.messages.some((message) => message.isPending)).toBe(true);
    firstPostDeferred.resolve();
    const message1 = await post1;
    expect(String(message1.body)).toInclude("blocked post");
});

test("store.insert different PY model having same JS model", async () => {
    await start();
    const store = getService("mail.store");
    const data = {
        "discuss.channel": [
            { id: 1, name: "General" },
            { id: 2, name: "Sales" },
        ],
        "mail.thread": [
            { id: 1, model: "discuss.channel" },
            { id: 3, name: "R&D", model: "discuss.channel" },
        ],
    };

    store.insert(data);
    expect(store.Thread.records).toHaveLength(6); // 3 mailboxes + 3 channels
    expect(Boolean(store.Thread.get({ id: 1, model: "discuss.channel" }))).toBe(true);
    expect(Boolean(store.Thread.get({ id: 2, model: "discuss.channel" }))).toBe(true);
    expect(Boolean(store.Thread.get({ id: 3, model: "discuss.channel" }))).toBe(true);
});
