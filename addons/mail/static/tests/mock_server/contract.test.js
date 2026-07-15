/**
 * JS half of the Store serialization drift gate (audit finding F3).
 *
 * The python half (mail/tests/test_mock_server_contract.py) seeds the same
 * scenario, calls the REAL controllers and asserts the same committed
 * field-name sets from the same file (contract/store_shapes.js). If either
 * implementation drifts — a server-side Store change the mock does not mirror,
 * or a mock change the server does not have — one of the two suites fails and
 * the diff names the scenario, model and fields.
 *
 * Only field-name sets are pinned (values are unstable: ids, datetimes,
 * access tokens); a few stable values are asserted inline to pin the scenario
 * itself. See the python module docstring for the regeneration workflow.
 */
import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import storeContract from "@mail/../tests/mock_server/contract/store_shapes";
import { describe, expect, test } from "@odoo/hoot";
import { Command, serverState } from "@web/../tests/web_test_helpers";
import { rpc } from "@web/core/network/rpc";

describe.current.tags("desktop");
defineMailModels();

const { gated_models: GATED_MODELS, scenarios: EXPECTED } = storeContract;

/** Reduce a Store payload to { model: sorted union of field names } for gated models. */
function payloadShape(payload) {
    const shape = {};
    for (const [modelName, records] of Object.entries(payload)) {
        if (!GATED_MODELS.includes(modelName)) {
            continue;
        }
        const keys = new Set();
        for (const record of Array.isArray(records) ? records : [records]) {
            for (const key of Object.keys(record)) {
                keys.add(key);
            }
        }
        shape[modelName] = [...keys].sort();
    }
    return shape;
}

/**
 * Assert one scenario's payload against the committed shapes, model by model
 * (small, complete diffs naming the drifted model instead of one giant
 * object diff).
 */
function expectShape(payload, expectedShape) {
    const shape = payloadShape(payload);
    const models = [
        ...new Set([...Object.keys(shape), ...Object.keys(expectedShape)]),
    ].sort();
    for (const model of models) {
        const actual = shape[model] ?? [];
        const expected = expectedShape[model] ?? [];
        const missing = expected.filter((field) => !actual.includes(field));
        const extra = actual.filter((field) => !expected.includes(field));
        // flattened to one short string per model so a failure prints the
        // exact drift on a single Expected/Received line pair — readable in
        // any log excerpt, unlike a multi-page array diff
        expect(
            `${model} missing=[${missing.join(",")}] extra=[${extra.join(",")}]`,
        ).toBe(`${model} missing=[] extra=[]`, {
            message: `Store model '${model}' drifted from the committed contract (store_shapes.js); fields the mock lacks are 'missing', fields it over-emits are 'extra'`,
        });
    }
}

/**
 * Seed the exact scenario of the python test: a second user, a channel with
 * both members, a plain message, a message with an attachment, a reply, some
 * reactions, and a chatter record with a follower and an attachment.
 */
async function seedContractScenario() {
    const pyEnv = await startServer();
    const bobPartnerId = pyEnv["res.partner"].create({ name: "Bob Contract" });
    pyEnv["res.users"].create({
        login: "contract_bob",
        name: "Bob Contract",
        partner_id: bobPartnerId,
    });
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: bobPartnerId }),
        ],
        channel_type: "channel",
        name: "Contract Channel",
    });
    const [subtypeCommentId] = pyEnv["mail.message.subtype"].search([
        ["subtype_xmlid", "=", "mail.mt_comment"],
    ]);
    const messageId = pyEnv["mail.message"].create({
        author_id: serverState.partnerId,
        body: "Hello world",
        message_type: "comment",
        model: "discuss.channel",
        res_id: channelId,
        subtype_id: subtypeCommentId,
    });
    const attachmentId = pyEnv["ir.attachment"].create({
        mimetype: "text/plain",
        name: "contract.txt",
        res_id: channelId,
        res_model: "discuss.channel",
    });
    pyEnv["mail.message"].create({
        attachment_ids: [attachmentId],
        author_id: bobPartnerId,
        body: "With attachment",
        message_type: "comment",
        model: "discuss.channel",
        res_id: channelId,
        subtype_id: subtypeCommentId,
    });
    pyEnv["mail.message"].create({
        author_id: serverState.partnerId,
        body: "A reply",
        message_type: "comment",
        model: "discuss.channel",
        parent_id: messageId,
        res_id: channelId,
        subtype_id: subtypeCommentId,
    });
    pyEnv["mail.message.reaction"].create([
        { content: "👍", message_id: messageId, partner_id: serverState.partnerId },
        { content: "👍", message_id: messageId, partner_id: bobPartnerId },
        { content: "😂", message_id: messageId, partner_id: bobPartnerId },
    ]);
    // chatter thread: a record with a follower and an attachment
    const recordId = pyEnv["res.partner"].create({ name: "Contract Customer" });
    pyEnv["mail.followers"].create({
        display_name: "Bob Contract",
        partner_id: bobPartnerId,
        res_id: recordId,
        res_model: "res.partner",
    });
    pyEnv["ir.attachment"].create({
        mimetype: "text/plain",
        name: "chatter.txt",
        res_id: recordId,
        res_model: "res.partner",
    });
    await start();
    return { bobPartnerId, channelId, recordId };
}

test("contract file covers exactly the scenarios this suite replays", async () => {
    expect(Object.keys(EXPECTED).sort()).toEqual([
        "channel_members",
        "channel_messages",
        "channels_as_member",
        "chatter_thread",
        "get_or_create_chat",
        "init_messaging",
        "message_post",
    ]);
});

test("mock /mail/data init_messaging matches the committed store contract", async () => {
    await seedContractScenario();
    const payload = await rpc("/mail/data", { fetch_params: ["init_messaging"] });
    expectShape(payload, EXPECTED.init_messaging);
});

test("mock /mail/data channels_as_member matches the committed store contract", async () => {
    await seedContractScenario();
    const payload = await rpc("/mail/data", { fetch_params: ["channels_as_member"] });
    // stable values pinning the scenario itself
    const channel = payload["discuss.channel"].find(
        (c) => c.name === "Contract Channel",
    );
    expect(channel.channel_type).toBe("channel");
    expectShape(payload, EXPECTED.channels_as_member);
});

test("mock /mail/data mail.thread (chatter) matches the committed store contract", async () => {
    const { recordId } = await seedContractScenario();
    const payload = await rpc("/mail/data", {
        fetch_params: [
            [
                "mail.thread",
                {
                    request_list: ["followers", "attachments"],
                    thread_id: recordId,
                    thread_model: "res.partner",
                },
            ],
        ],
    });
    expectShape(payload, EXPECTED.chatter_thread);
});

test("mock /discuss/channel/messages matches the committed store contract", async () => {
    const { channelId } = await seedContractScenario();
    const { data } = await rpc("/discuss/channel/messages", {
        channel_id: channelId,
        fetch_params: { limit: 30 },
    });
    expectShape(data, EXPECTED.channel_messages);
});

test("mock /discuss/channel/members matches the committed store contract", async () => {
    const { channelId } = await seedContractScenario();
    const payload = await rpc("/discuss/channel/members", {
        channel_id: channelId,
        known_member_ids: [],
    });
    expectShape(payload, EXPECTED.channel_members);
});

test("mock /mail/message/post matches the committed store contract", async () => {
    const { channelId } = await seedContractScenario();
    const { store_data } = await rpc("/mail/message/post", {
        post_data: {
            body: "posted from contract",
            message_type: "comment",
            subtype_xmlid: "mail.mt_comment",
        },
        thread_id: channelId,
        thread_model: "discuss.channel",
    });
    const posted = store_data["mail.message"];
    expect(JSON.stringify(posted.map((m) => m.body))).toInclude("posted from contract");
    expectShape(store_data, EXPECTED.message_post);
});

test("mock /mail/action get_or_create_chat matches the committed store contract", async () => {
    const { bobPartnerId } = await seedContractScenario();
    const payload = await rpc("/mail/action", {
        fetch_params: [
            [
                "/discuss/get_or_create_chat",
                { partners_to: [bobPartnerId] },
                "contract-data-id",
            ],
        ],
    });
    expectShape(payload, EXPECTED.get_or_create_chat);
});
