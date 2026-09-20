/** @odoo-module native */
import { onWillDestroy, reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

import { trace } from "../../common/approval_trace.js";

const UNGATED = { gated: false, approved: true, request: false, steps: [] };

/**
 * The approval state of one button on one record, kept current across loads and
 * saves of the record's model.
 *
 * @param {Object} params
 * @param {() => any} params.getRecord
 * @param {string|false} params.method
 * @param {string|false} params.action
 */
export function useApprovalButton({ getRecord, method, action }) {
    const orm = useService("orm");
    const notification = useService("notification");
    const approvalButton = useService("approval_button");
    const gate = reactive({ result: null, syncing: false });

    function buttonArgs() {
        const record = getRecord();
        return [
            record.resModel,
            record.resId || false,
            method || false,
            action || false,
        ];
    }

    async function load() {
        const [model, resId, buttonMethod, actionId] = buttonArgs();
        gate.syncing = true;
        try {
            gate.result = await approvalButton.load({
                model,
                res_id: resId,
                method: buttonMethod,
                action_id: actionId,
            });
        } catch (error) {
            // Failing open is deliberate -- a gate that cannot be read must not
            // block the record -- but it used to fail open in silence, which reads
            // to a developer exactly like a button that was never gated.
            browser.console.warn(
                `approval: the gate on ${model}#${resId} could not be read ` +
                    `(${error?.name || "Error"}), so the button is shown ungated.`,
            );
            trace.note("button", "load_failed", {
                model,
                res_id: resId,
                method: buttonMethod,
                action: actionId,
                error: error?.name || "Error",
            });
            gate.result = UNGATED;
        } finally {
            gate.syncing = false;
        }
        trace.event("button", "loaded", {
            model,
            res_id: resId,
            method: buttonMethod,
            gated: gate.result?.gated,
            approved: gate.result?.approved,
            request: gate.result?.request?.id || false,
            steps: gate.result?.steps?.length || 0,
        });
    }

    async function replaceWith(promise) {
        gate.syncing = true;
        try {
            gate.result = await promise;
        } finally {
            gate.syncing = false;
        }
        await getRecord().model.root.load();
    }

    async function saveRecord() {
        const record = getRecord();
        if (!record.resId) {
            const root = record.model.root;
            return ("resId" in root ? root : record).save();
        }
        return record.isDirty ? record.save() : true;
    }

    const model = getRecord().model;
    trace.event("button", "hooked", {
        model: getRecord().resModel,
        method: method || false,
        action: action || false,
        subscribes: Boolean(model?.subscribeLifecycle),
    });
    if (model?.subscribeLifecycle) {
        const unsubscribe = [
            model.subscribeLifecycle("onRootLoaded", () => {
                trace.event("button", "reload", { on: "onRootLoaded" });
                return load();
            }),
            model.subscribeLifecycle("onRecordSaved", () => {
                trace.event("button", "reload", { on: "onRecordSaved" });
                return load();
            }),
        ];
        onWillDestroy(() => unsubscribe.forEach((dispose) => dispose()));
    }
    load();

    return Object.assign(gate, {
        load,
        hasRecord: () => Boolean(getRecord().resId),
        async check() {
            if ((await saveRecord()) === false) {
                return false;
            }
            const { approved } = await orm.call(
                "approval.binding",
                "check_button_approval",
                buttonArgs(),
            );
            trace.note("button", "checked", {
                model: getRecord().resModel,
                res_id: getRecord().resId || false,
                method: method || false,
                approved,
            });
            if (!approved) {
                notification.add(_t("This needs an approval before it can run."), {
                    type: "warning",
                });
            }
            load();
            return approved;
        },
        decide(approve, stepId = false) {
            return trace.span(
                "button",
                "decided",
                { model: getRecord().resModel, approve, step: stepId },
                () =>
                    replaceWith(
                        orm.call("approval.binding", "action_decide_approval", [
                            ...buttonArgs(),
                            approve,
                            stepId,
                        ]),
                    ),
            );
        },
        withdraw(approverId, stepId = false) {
            return trace.span(
                "button",
                "withdrawn",
                { model: getRecord().resModel, approver: approverId, step: stepId },
                () =>
                    replaceWith(
                        orm.call("approval.binding", "action_withdraw_decision", [
                            ...buttonArgs(),
                            approverId,
                            stepId,
                        ]),
                    ),
            );
        },
    });
}
