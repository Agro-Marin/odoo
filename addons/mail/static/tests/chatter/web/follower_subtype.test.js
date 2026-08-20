import {
    click,
    contains,
    defineMailModels,
    openFormView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { getService, onRpc, serverState } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("simplest layout of a followed subtype", async () => {
    const pyEnv = await startServer();
    const subtypeId = pyEnv["mail.message.subtype"].create({
        default: true,
        name: "TestSubtype",
    });
    pyEnv["mail.followers"].create({
        display_name: "François Perusse",
        partner_id: serverState.partnerId,
        res_model: "res.partner",
        res_id: serverState.partnerId,
        subtype_ids: [subtypeId],
    });
    await start();
    await openFormView("res.partner", serverState.partnerId);
    await click(".o-mail-Followers-button");
    await click("[title='Edit subscription']");
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] label`,
        { text: "TestSubtype" },
    );
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] input[type='checkbox']:checked`,
    );
});

test("simplest layout of a not followed subtype", async () => {
    const pyEnv = await startServer();
    const subtypeId = pyEnv["mail.message.subtype"].create({
        default: true,
        name: "TestSubtype",
    });
    pyEnv["mail.followers"].create({
        display_name: "François Perusse",
        partner_id: serverState.partnerId,
        res_model: "res.partner",
        res_id: serverState.partnerId,
    });
    await start();
    await openFormView("res.partner", serverState.partnerId);
    await click(".o-mail-Followers-button");
    await click("[title='Edit subscription']");
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] input[type='checkbox']:not(:checked)`,
    );
});

test("toggle follower subtype checkbox", async () => {
    const pyEnv = await startServer();
    const subtypeId = pyEnv["mail.message.subtype"].create({
        default: true,
        name: "TestSubtype",
    });
    pyEnv["mail.followers"].create({
        display_name: "François Perusse",
        partner_id: serverState.partnerId,
        res_model: "res.partner",
        res_id: serverState.partnerId,
    });
    await start();
    await openFormView("res.partner", serverState.partnerId);
    await click(".o-mail-Followers-button");
    await click("[title='Edit subscription']");
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] input[type='checkbox']:not(:checked)`,
    );
    await click(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] input[type='checkbox']`,
    );
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] input[type='checkbox']:checked`,
    );
    await click(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] input[type='checkbox']`,
    );
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] input[type='checkbox']:not(:checked)`,
    );
});

test("follower subtype apply", async () => {
    const pyEnv = await startServer();
    const subtypeId1 = pyEnv["mail.message.subtype"].create({
        default: true,
        name: "TestSubtype1",
    });
    const subtypeId2 = pyEnv["mail.message.subtype"].create({
        default: true,
        name: "TestSubtype2",
    });
    pyEnv["mail.followers"].create({
        display_name: "François Perusse",
        partner_id: serverState.partnerId,
        res_model: "res.partner",
        res_id: serverState.partnerId,
        subtype_ids: [subtypeId1],
    });
    await start();
    await openFormView("res.partner", serverState.partnerId);
    await click(".o-mail-Followers-button");
    await click("[title='Edit subscription']");
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId1}'] input[type='checkbox']:checked`,
    );
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId2}'] input[type='checkbox']:not(:checked)`,
    );
    await click(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId1}'] input[type='checkbox']`,
    );
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId1}'] input[type='checkbox']:not(:checked)`,
    );
    await click(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId2}'] input[type='checkbox']`,
    );
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId2}'] input[type='checkbox']:checked`,
    );
    await click(".modal-footer button", { text: "Apply" });
    await contains(".o_notification", {
        text: "The subscription preferences were successfully applied.",
    });
});

test("apply keeps the subtypes the dialog does not manage", async () => {
    // `_mail_get_message_subtypes` hides some of a follower's subtypes
    // (`hidden`, or a model-specific exclusion such as `project.task`'s rating
    // subtype). Apply rewrites the whole subscription, so a dialog that submits
    // only what it rendered silently revokes the rest.
    const pyEnv = await startServer();
    const shownId = pyEnv["mail.message.subtype"].create({ name: "Shown" });
    const hiddenId = pyEnv["mail.message.subtype"].create({
        hidden: true,
        name: "Hidden",
    });
    pyEnv["mail.followers"].create({
        display_name: "François Perusse",
        partner_id: serverState.partnerId,
        res_model: "res.partner",
        res_id: serverState.partnerId,
        subtype_ids: [shownId, hiddenId],
    });
    let sent;
    onRpc("res.partner", "message_subscribe", ({ kwargs }) => {
        sent = kwargs.subtype_ids;
        return true;
    });
    await start();
    await openFormView("res.partner", serverState.partnerId);
    await click(".o-mail-Followers-button");
    await click("[title='Edit subscription']");
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${shownId}'] input:checked`,
    );
    await contains(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${hiddenId}']`,
        { count: 0 },
    );
    await click(".modal-footer button", { text: "Apply" });
    await contains(".o_notification");
    expect([...sent].sort()).toEqual([shownId, hiddenId].sort());
});

test("cancel does not change the subscription", async () => {
    const pyEnv = await startServer();
    const subtypeId = pyEnv["mail.message.subtype"].create({ name: "TestSubtype" });
    const followerId = pyEnv["mail.followers"].create({
        display_name: "François Perusse",
        partner_id: serverState.partnerId,
        res_model: "res.partner",
        res_id: serverState.partnerId,
        subtype_ids: [subtypeId],
    });
    onRpc("res.partner", "message_subscribe", () => {
        expect.step("message_subscribe");
        return true;
    });
    await start();
    await openFormView("res.partner", serverState.partnerId);
    await click(".o-mail-Followers-button");
    await click("[title='Edit subscription']");
    await click(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] input`,
    );
    await click(".modal-footer button", { text: "Cancel" });
    expect.verifySteps([]);
    const follower = getService("mail.store")["mail.followers"].get(followerId);
    expect(follower.subtype_ids.map((subtype) => subtype.id)).toEqual([subtypeId]);
});

test("unchecking every subtype unsubscribes the follower", async () => {
    const pyEnv = await startServer();
    const subtypeId = pyEnv["mail.message.subtype"].create({ name: "TestSubtype" });
    pyEnv["mail.followers"].create({
        display_name: "François Perusse",
        partner_id: serverState.partnerId,
        res_model: "res.partner",
        res_id: serverState.partnerId,
        subtype_ids: [subtypeId],
    });
    onRpc("/mail/thread/unsubscribe", () => expect.step("unsubscribe"));
    onRpc("res.partner", "message_subscribe", () => {
        expect.step("message_subscribe");
        return true;
    });
    await start();
    await openFormView("res.partner", serverState.partnerId);
    await click(".o-mail-Followers-button");
    await click("[title='Edit subscription']");
    await click(
        `.o-mail-FollowerSubtypeDialog-subtype[data-follower-subtype-id='${subtypeId}'] input`,
    );
    await click(".modal-footer button", { text: "Apply" });
    await expect.waitForSteps(["unsubscribe"]);
});

test("apply keeps unmanaged subtypes when the server sends them as bare ids", async () => {
    // The real `/mail/read_subscription_data` builds its payload with
    // `.add(follower, ["subtype_ids"])`, which emits the relation as plain ids and adds NO
    // record for a subtype the dialog does not render. The mock uses `Store.many(...)`
    // instead, which adds full records -- so the mock-shaped test above does not pin the
    // production contract on its own.
    const pyEnv = await startServer();
    const shownId = pyEnv["mail.message.subtype"].create({ name: "Shown" });
    const hiddenId = pyEnv["mail.message.subtype"].create({
        hidden: true,
        name: "Hidden",
    });
    pyEnv["mail.followers"].create({
        display_name: "François Perusse",
        partner_id: serverState.partnerId,
        res_model: "res.partner",
        res_id: serverState.partnerId,
        subtype_ids: [shownId, hiddenId],
    });
    onRpc("/mail/read_subscription_data", async (request) => {
        const { params } = await request.json();
        return {
            store_data: {
                "mail.message.subtype": [{ id: shownId, name: "Shown" }],
                "mail.followers": [
                    { id: params.follower_id, subtype_ids: [shownId, hiddenId] },
                ],
            },
            subtype_ids: [shownId],
        };
    });
    let sent;
    onRpc("res.partner", "message_subscribe", ({ kwargs }) => {
        sent = kwargs.subtype_ids;
        return true;
    });
    await start();
    await openFormView("res.partner", serverState.partnerId);
    await click(".o-mail-Followers-button");
    await click("[title='Edit subscription']");
    await contains(".o-mail-FollowerSubtypeDialog-subtype", { count: 1 });
    await click(".modal-footer button", { text: "Apply" });
    await contains(".o_notification");
    expect([...sent].sort()).toEqual([shownId, hiddenId].sort());
});
