/** @odoo-module native */
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";

const FIELDS = [
    "unit_amount",
    "effective_hours",
    "allocated_hours",
    "remaining_hours",
    "total_hours_spent",
    "subtask_effective_hours",
    "overtime",
    "number_hours",
    "difference",
    "timesheet_unit_amount",
];

export function patchGraphModel(Model) {
    patch(Model.prototype, {
        /**
         * @override
         */
        _getProcessedDataPoints() {
            const factor = user.activeCompany.timesheet_uom_factor || 1;
            if (factor !== 1 && FIELDS.includes(this.metaData.measure)) {
                for (const dataPt of this.dataPoints) {
                    dataPt.value *= factor;
                }
            }
            return super._getProcessedDataPoints(...arguments);
        },
    });
}
