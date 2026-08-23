import { describe, expect, test } from "@odoo/hoot";
import { DateTime } from "luxon";

import { serializeDate } from "@web/core/l10n/dates";
import { Deferred } from "@odoo/hoot-mock";

import { defineApprovalsModels } from "@approval/../tests/approvals_test_helpers";
import {
    click,
    contains,
    openFormView,
    openListView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import {
    asyncStep,
    onRpc,
    serverState,
    waitForSteps,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineApprovalsModels();

function setupApprovalActivity(pyEnv, { userId = serverState.userId } = {}) {
    pyEnv["approval.request"].create({});
    pyEnv["approval.request"].create({});
    const requestId = pyEnv["approval.request"].create({});
    const approverId = pyEnv["approval.approver"].create({
        request_id: requestId,
        state: "pending",
        user_id: userId,
    });
    pyEnv["mail.activity"].create({
        can_write: true,
        res_id: requestId,
        res_model: "approval.request",
        user_id: userId,
    });
    expect(approverId).not.toBe(requestId);
    return { requestId, approverId };
}

test("activity with approval to be made by logged user", async () => {
    const pyEnv = await startServer();
    const { requestId } = setupApprovalActivity(pyEnv);
    await start();
    await openFormView("approval.request", requestId);
    await contains(".o-mail-Activity");
    await contains(".o-mail-Activity-sidebar");
    await contains(".o-mail-Activity-user");
    await contains(".o-mail-Activity-note", { count: 0 });
    await contains(".o-mail-Activity-details", { count: 0 });
    await contains(".o-mail-Activity-mailTemplates", { count: 0 });
    await contains(".o-mail-Activity .btn", { count: 0, text: "Edit" });
    await contains(".o-mail-Activity .btn", { count: 0, text: "Cancel" });
    await contains(".o-mail-Activity .btn", { count: 0, text: "Mark Done" });
    await contains(".o-mail-Activity .btn", { count: 0, text: "Upload Document" });
    await contains(".o-mail-Activity button", { text: "Approve" });
    await contains(".o-mail-Activity button", { text: "Refuse" });
});

test("activity with approval to be made by another user", async () => {
    const pyEnv = await startServer();
    const userId = pyEnv["res.users"].create({
        partner_id: pyEnv["res.partner"].create({ name: "Mike" }),
    });
    const { requestId } = setupApprovalActivity(pyEnv, { userId });
    await start();
    await openFormView("approval.request", requestId);
    await contains(".o-mail-Activity");
    await contains(".o-mail-Activity-sidebar");
    await contains(".o-mail-Activity-user");
    await contains(".o-mail-Activity-note", { count: 0 });
    await contains(".o-mail-Activity-details", { count: 0 });
    await contains(".o-mail-Activity-mailTemplates", { count: 0 });
    await contains(".o-mail-Activity .btn", { count: 0, text: "Edit" });
    await contains(".o-mail-Activity .btn", { count: 0, text: "Cancel" });
    await contains(".o-mail-Activity .btn", { count: 0, text: "Mark Done" });
    await contains(".o-mail-Activity .btn", { count: 0, text: "Upload Document" });
    await contains(".o-mail-Activity button", { count: 1, text: "Approve" });
    await contains(".o-mail-Activity button", { count: 1, text: "Refuse" });
});

test("approve approval sends the APPROVER id, not the request id", async () => {
    const pyEnv = await startServer();
    const { requestId, approverId } = setupApprovalActivity(pyEnv);
    const def = new Deferred();
    onRpc("approval.approver", "action_approve", (args) => {
        expect(args.args.length).toBe(1);
        expect(args.args[0]).toBe(approverId);
        asyncStep("action_approve");
        def.resolve();
    });
    await start();
    await openFormView("approval.request", requestId);
    await click(".o-mail-Activity button", { text: "Approve" });
    await def;
    await waitForSteps(["action_approve"]);
});

test("refuse opens the decision wizard and keeps the activity", async () => {
    const pyEnv = await startServer();
    const { requestId, approverId } = setupApprovalActivity(pyEnv);
    onRpc("approval.approver", "action_refuse", (args) => {
        expect(args.args.length).toBe(1);
        expect(args.args[0]).toBe(approverId);
        asyncStep("action_refuse");
    });
    await start();
    await openFormView("approval.request", requestId);
    await click(".o-mail-Activity button", { text: "Refuse" });
    await waitForSteps(["action_refuse"]);

    await contains(".o_dialog");
    await contains(".o-mail-Activity button", { count: 1, text: "Approve" });
    await contains(".o-mail-Activity button", { count: 1, text: "Refuse" });
});

test("cancelling the decision wizard leaves the approval undecided", async () => {
    const pyEnv = await startServer();
    const { requestId } = setupApprovalActivity(pyEnv);
    await start();
    await openFormView("approval.request", requestId);
    await click(".o-mail-Activity button", { text: "Refuse" });
    await contains(".o_dialog");

    await click(".o_dialog footer button", { text: "Cancel" });

    await contains(".o_dialog", { count: 0 });
    await contains(".o-mail-Activity button", { text: "Approve" });
    await contains(".o-mail-Activity button", { text: "Refuse" });
});

test("approval activities hide Edit and Mark Done in the activity popover", async () => {
    const pyEnv = await startServer();
    const requestId = pyEnv["approval.request"].create({});
    pyEnv["approval.approver"].create({
        request_id: requestId,
        state: "pending",
        user_id: serverState.userId,
    });
    const activityTypeId = pyEnv["mail.activity.type"].create({});
    const activityId = pyEnv["mail.activity"].create({
        can_write: true,
        res_id: requestId,
        res_model: "approval.request",
        user_id: serverState.userId,
        create_uid: serverState.userId,
        activity_type_id: activityTypeId,
        state: "today",
        date_deadline: serializeDate(DateTime.now()),
    });
    pyEnv["approval.request"].write([requestId], {
        activity_ids: [activityId],
        activity_state: "today",
    });
    await start();
    await openListView("approval.request");
    await click(".o-mail-ActivityButton");

    await contains(".o-mail-ActivityListPopoverItem");
    await contains(".o-mail-ActivityListPopoverItem-markAsDone", { count: 0 });
    await contains(".o-mail-ActivityListPopoverItem button", { text: "Approve" });
    await contains(".o-mail-ActivityListPopoverItem button", { text: "Refuse" });
});

test("non-approval activities keep Mark Done in the popover", async () => {
    const pyEnv = await startServer();
    const requestId = pyEnv["approval.request"].create({});
    const activityTypeId = pyEnv["mail.activity.type"].create({});
    const activityId = pyEnv["mail.activity"].create({
        can_write: true,
        res_id: requestId,
        res_model: "approval.request",
        user_id: serverState.userId,
        create_uid: serverState.userId,
        activity_type_id: activityTypeId,
        state: "today",
        date_deadline: serializeDate(DateTime.now()),
    });
    pyEnv["approval.request"].write([requestId], {
        activity_ids: [activityId],
        activity_state: "today",
    });
    await start();
    await openListView("approval.request");
    await click(".o-mail-ActivityButton");

    await contains(".o-mail-ActivityListPopoverItem");
    await contains(".o-mail-ActivityListPopoverItem-markAsDone");
    await contains(".o-mail-ActivityListPopoverItem button", {
        count: 0,
        text: "Approve",
    });
});
