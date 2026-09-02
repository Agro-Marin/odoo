/** @odoo-module native */
import { Component } from "@odoo/owl";
import { DateTimeInput } from "@web/components/datetime/datetime_input";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { serializeDate } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets";
const { DateTime } = luxon;

export class MailActivityListRescheduleDropdown extends Component {
    static components = { DateTimeInput, Dropdown, DropdownItem };
    static props = {
        ...standardWidgetProps,
    };
    static template = "mail.MailActivityListRescheduleDropdown";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const today = DateTime.now().startOf("day");
        this.targetDays = {
            today: {
                displayDay: today.weekdayShort,
                actionName: "action_reschedule_today",
            },
            tomorrow: {
                displayDay: today.plus({ days: 1 }).weekdayShort,
                actionName: "action_reschedule_tomorrow",
            },
            nextWeek: {
                displayDay: today.plus({ weeks: 1 }).startOf("week").weekdayShort,
                actionName: "action_reschedule_nextweek",
            },
            customDate: {
                actionName: "action_reschedule_customdate",
            },
        };
    }

    /**
     * @param {MouseEvent|false} click
     * @param {string} actionName
     * @param {import("@web/core/l10n/luxon").DateTime} [customDate] the date
     *  picked in the dropdown; clearing the picker calls back with nothing,
     *  which must not reschedule anything.
     */
    async rescheduleActivity(click, actionName, customDate) {
        if (actionName === this.targetDays.customDate.actionName && !customDate) {
            return this.props.record;
        }
        await this.action.doActionButton({
            type: "object",
            name: actionName,
            resModel: this.props.record.resModel,
            resId: this.props.record.resId,
            ...(customDate ? { args: JSON.stringify([serializeDate(customDate)]) } : {}),
            onClose: async () => {
                await this.props.record.model.root.load();
                this.props.record.model.notify();
            },
        });
        return this.props.record;
    }
}

export class MailActivityMixinListRescheduleDropdown extends MailActivityListRescheduleDropdown {
    static template = "mail.MailActivityMixinListRescheduleDropdown";
    setup() {
        super.setup();
        this.targetDays.today.actionName = "action_reschedule_my_next_today";
        this.targetDays.tomorrow.actionName = "action_reschedule_my_next_tomorrow";
        this.targetDays.nextWeek.actionName = "action_reschedule_my_next_nextweek";
        this.targetDays.customDate.actionName = "action_reschedule_my_next_customdate";
    }
}

registry.category("view_widgets").add("mail_activity_list_reschedule_dropdown", {
    component: MailActivityListRescheduleDropdown,
    listViewWidth: [50, 100],
});

registry.category("view_widgets").add("mail_activity_mixin_list_reschedule_dropdown", {
    component: MailActivityMixinListRescheduleDropdown,
    listViewWidth: [50, 100],
});
