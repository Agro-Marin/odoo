import {
    click,
    contains,
    defineMailModels,
    insertText,
    openDiscuss,
    scroll,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { Deferred, tick } from "@odoo/hoot-mock";
import {
    asyncStep,
    getService,
    onRpc,
    waitForSteps,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

const GIFS = [
    {
        id: "1",
        title: "",
        media_formats: {
            tinygif: {
                url: "https://media.tenor.com/np49Y1vrJO8AAAAM/crying-cry.gif",
                dims: [220, 190],
                size: 1007885,
                duration: 0,
                preview: "",
            },
        },
        created: 1654414453.782169,
        content_description: "Cry GIF",
        itemurl: "https://tenor.com/view/cry-gif-25866484",
        url: "https://tenor.com/bUHdw.gif",
        tags: ["cry"],
        flags: [],
        hasaudio: false,
    },
];

test.todo(
    "gif picker resets the pagination token when the search term changes (bd882ff4)",
    async () => {
        const pyEnv = await startServer();
        const channelId = pyEnv["discuss.channel"].create({ name: "General" });
        onRpc("/discuss/gif/categories", () => ({ tags: [], locale: "en_US" }));
        onRpc("/discuss/gif/search", async (request) => {
            const { params } = await request.json();
            asyncStep(`search:${params.search_term}:${params.position ?? ""}`);
            const next =
                params.search_term === "cat" && !params.position ? "TOKEN_CAT" : "";
            return { results: GIFS, next };
        });
        await start();
        await openDiscuss(channelId);
        await click("button[title='Add GIFs']");
        await insertText("input[placeholder='Search for a GIF']", "cat");
        await waitForSteps(["search:cat:"]);
        await scroll(".o-discuss-GifPicker-content", "bottom");
        await waitForSteps(["search:cat:TOKEN_CAT"]);
        await insertText("input[placeholder='Search for a GIF']", "dog", {
            replace: true,
        });
        await waitForSteps(["search:dog:"]);
        await contains(".o-discuss-Gif");
    },
);

test.todo(
    "rtc: hasPendingRequest is released after a failed join (bd882ff4)",
    async () => {
        throw new Error(
            "regression skeleton — implement per scenario above and run locally",
        );
    },
);

test.todo(
    "chat hub: initPromise settles even if the restore fetch fails (bd882ff4)",
    async () => {
        throw new Error(
            "regression skeleton — implement per scenario above and run locally",
        );
    },
);

test.todo(
    "voice recorder: a failed init resets isActionPending and stops the mic (bd882ff4)",
    async () => {
        throw new Error(
            "regression skeleton — implement per scenario above and run locally",
        );
    },
);

test("discuss: markingAsRead stays set for the whole in-flight RPC (bd882ff4)", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    const bobPartnerId = pyEnv["res.partner"].create({ name: "Bob" });
    for (let i = 0; i < 3; ++i) {
        pyEnv["mail.message"].create({
            author_id: bobPartnerId,
            body: `m${i}`,
            model: "discuss.channel",
            res_id: channelId,
        });
    }
    const gates = [];
    onRpc("/discuss/channel/mark_as_read", async () => {
        const deferred = new Deferred();
        gates.push(deferred);
        await deferred;
        return true;
    });
    await start();
    await openDiscuss(channelId);
    const store = getService("mail.store");
    const thread = store.Thread.insert({ model: "discuss.channel", id: channelId });

    while (gates.length) {
        gates.pop().resolve(true);
    }
    await tick();
    await tick();

    thread.markAsRead();
    await tick();
    expect(gates.length).toBe(1);
    expect(thread.markingAsRead).toBe(true);

    thread.markAsRead();
    await tick();
    gates[0].resolve(true);
    await tick();
    await tick();

    expect(gates.length).toBe(2);
    expect(thread.markingAsRead).toBe(true);
    gates[1].resolve(true);
    await tick();
});
