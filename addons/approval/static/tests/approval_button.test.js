import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    mockService,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Partner extends models.Model {
    _name = "partner";

    name = fields.Char();

    _records = [{ id: 1, name: "first" }];

    async get_views() {
        const result = await super.get_views(...arguments);
        for (const info of Object.values(result.models)) {
            info.has_approval_bindings = true;
        }
        return result;
    }
}

class Plain extends models.Model {
    _name = "plain";

    name = fields.Char();

    _records = [{ id: 1, name: "ungated" }];
}

defineModels([Partner, Plain]);
defineMailModels();

function step(values = {}) {
    return {
        id: 1,
        name: "Managers",
        sequence: 10,
        minimum: 1,
        exclusive: false,
        can_decide: true,
        decisions: [],
        ...values,
    };
}

function result(values = {}) {
    return { gated: true, approved: false, request: false, steps: [step()], ...values };
}

const approvedDecision = {
    approver_id: 7,
    user_id: 2,
    user_name: "Mitchell Admin",
    state: "approved",
    date: "2026-09-10 10:00:00",
    can_withdraw: true,
};

const buttonsArch = `
    <form>
        <header>
            <button type="object" name="method_a" string="A"/>
            <button type="object" name="method_b" string="B"/>
        </header>
        <field name="name"/>
    </form>`;

const oneButtonArch = `<form><header><button type="object" name="method_a" string="A"/></header></form>`;

test("gated buttons ask for their approvals in one call", async () => {
    onRpc("approval.binding", "get_button_approvals", ({ args }) => {
        expect.step(args[0].map((spec) => spec.method));
        return args[0].map(() => result());
    });
    await mountView({ type: "form", resModel: "partner", resId: 1, arch: buttonsArch });
    expect(".o_approval_button").toHaveCount(2);
    expect(".o_approval_button_waiting").toHaveCount(2);
    expect.verifySteps([["method_a", "method_b"]]);
});

test("a model without bindings asks nothing", async () => {
    onRpc("approval.binding", "get_button_approvals", () => {
        expect.step("asked");
        return [];
    });
    await mountView({ type: "form", resModel: "plain", resId: 1, arch: buttonsArch });
    expect(".o_approval_button").toHaveCount(0);
    expect.verifySteps([]);
});

test("approving from the popover decides as the caller", async () => {
    let decided = false;
    const decidedResult = () =>
        result({
            approved: true,
            steps: [step({ can_decide: false, decisions: [approvedDecision] })],
        });
    onRpc("approval.binding", "get_button_approvals", ({ args }) =>
        args[0].map(() => (decided ? decidedResult() : result())),
    );
    onRpc("approval.binding", "action_decide_approval", ({ args }) => {
        expect.step(args);
        decided = true;
        return decidedResult();
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: oneButtonArch,
    });
    await contains(".o_approval_button").click();
    await contains(".o_approval_button_approve").click();
    expect.verifySteps([["partner", 1, "method_a", false, true]]);
    expect(".o_approval_button_decision.o_approval_button_approved").toHaveCount(1);
    expect(".o_approval_button_approve").toHaveCount(0);
});

test("withdrawing sends the decision's row", async () => {
    onRpc("approval.binding", "get_button_approvals", ({ args }) =>
        args[0].map(() => result({ steps: [step({ decisions: [approvedDecision] })] })),
    );
    onRpc("approval.binding", "action_withdraw_decision", ({ args }) => {
        expect.step(args);
        return result();
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: oneButtonArch,
    });
    await contains(".o_approval_button").click();
    await contains(".o_approval_button_withdraw").click();
    expect.verifySteps([["partner", 1, "method_a", false, 7]]);
});

test("a refusal that can be reopened offers to reopen it, and nothing to decide", async () => {
    onRpc("approval.binding", "get_button_approvals", ({ args }) =>
        args[0].map(() =>
            result({ request: { id: 5, state: "refused", can_reopen: true } }),
        ),
    );
    onRpc("approval.binding", "action_withdraw_decision", ({ args }) => {
        expect.step(args);
        return result();
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: oneButtonArch,
    });
    await contains(".o_approval_button").click();
    expect(".o_approval_button_approve").toHaveCount(0);
    await contains(".o_approval_button_reopen").click();
    expect.verifySteps([["partner", 1, "method_a", false, false]]);
});

test("an action button is checked before it runs, and does not run unapproved", async () => {
    let approved = false;
    mockService("action", {
        async doActionButton(params) {
            expect.step(`run ${params.name}`);
        },
    });
    onRpc("approval.binding", "get_button_approvals", ({ args }) =>
        args[0].map(() => result()),
    );
    onRpc("approval.binding", "check_button_approval", ({ args }) => {
        expect.step(`check ${args[3]}`);
        return { approved, request_id: 5 };
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `<form><header><button type="action" name="42" string="Go"/></header></form>`,
    });
    await contains("button[name='42'] span:first").click();
    expect.verifySteps(["check 42"]);
    approved = true;
    await contains("button[name='42'] span:first").click();
    expect.verifySteps(["check 42", "run 42"]);
});

test("an object button is not checked in the browser", async () => {
    mockService("action", {
        async doActionButton(params) {
            expect.step(`run ${params.name}`);
        },
    });
    onRpc("approval.binding", "get_button_approvals", ({ args }) =>
        args[0].map(() => result()),
    );
    onRpc("approval.binding", "check_button_approval", () => {
        expect.step("check");
        return { approved: true, request_id: false };
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: oneButtonArch,
    });
    await contains("button[name='method_a'] span:first").click();
    expect.verifySteps(["run method_a"]);
});
