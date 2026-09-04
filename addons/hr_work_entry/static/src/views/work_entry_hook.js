/** @odoo-module native */
import { onWillStart, useState } from "@odoo/owl";
import { serializeDate } from "@web/core/l10n/dates";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

export function useWorkEntry({ getEmployeeIds, getRange, onClose }) {
    const action = useService("action");
    const state = useState({ canRegenerate: false });

    onWillStart(async () => {
        state.canRegenerate = await user.hasGroup("hr.group_hr_manager");
    });

    return {
        state,
        onRegenerateWorkEntries: () => {
            const { start, end } = getRange();
            action.doAction("hr_work_entry.hr_work_entry_regeneration_wizard_action", {
                additionalContext: {
                    default_employee_ids: getEmployeeIds(),
                    date_start: serializeDate(start),
                    date_end: serializeDate(end),
                },
                onClose: onClose,
            });
        },
    };
}
