/** @odoo-module native */
import { onWillDestroy, reactive } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

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
        } catch {
            gate.result = UNGATED;
        } finally {
            gate.syncing = false;
        }
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
    if (model?.subscribeLifecycle) {
        const unsubscribe = [
            model.subscribeLifecycle("onRootLoaded", () => load()),
            model.subscribeLifecycle("onRecordSaved", () => load()),
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
            if (!approved) {
                notification.add(_t("This needs an approval before it can run."), {
                    type: "warning",
                });
            }
            load();
            return approved;
        },
        decide(approve) {
            return replaceWith(
                orm.call("approval.binding", "action_decide_approval", [
                    ...buttonArgs(),
                    approve,
                ]),
            );
        },
        withdraw(approverId) {
            return replaceWith(
                orm.call("approval.binding", "action_withdraw_decision", [
                    ...buttonArgs(),
                    approverId,
                ]),
            );
        },
    });
}
