/** @odoo-module native */
import { useService, useBus } from "@web/core/utils/hooks";
import { isNull } from "@web/views/view_utils";
import { KanbanRenderer } from "@web/views/kanban";
import { AccountReturnKanbanRecord } from "./account_return_kanban_record.js";
import { AccountReturnBaseKanbanRenderer } from "./account_return_base_kanban_renderer.js";
import { useDeleteRecords } from "@web/views/view_hook";

export class AccountReturnKanbanRenderer extends AccountReturnBaseKanbanRenderer {
    static template = "account.account_return_kanban_renderer";

    static props = [...KanbanRenderer.props];

    static components = {
        ...KanbanRenderer.components,
        AccountReturnKanbanRecord,
    };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.deleteRecordsWithConfirmation = useDeleteRecords(this.props.list.model);

        useBus(this.env.bus, "return_reload_model", (ev) => {
            const recordIds = ev.detail.resIds;
            let recordToReload = this.records.filter((record) =>
                recordIds.includes(record.resId),
            );
            for (let record of recordToReload) {
                record.model.load();
            }
        });
    }

    deleteRecord(record) {
        this.deleteRecordsWithConfirmation({}, [record]);
    }

    async openRecord(record, params) {
        if (record.context?.in_checks_view) {
            return;
        }
        const action = await this.orm.call(
            "account.return",
            "action_view_account_return",
            [record.resIds],
        );
        if (!action) return;
        return this.actionService.doAction(action);
    }

    get records() {
        const { list } = this.props;
        if (list.isGrouped) {
            return list.groups.flatMap((group) => group.list.records);
        } else {
            return list.records;
        }
    }

    get groups() {
        const { list } = this.props;
        if (!list.isGrouped) {
            return false;
        }

        return list.groups.map((group, i) => ({
            ...group,
            key: isNull(group.value) ? `group_key_${i}` : String(group.value),
        }));
    }
}
