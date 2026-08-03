/** @odoo-module native */
import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";
import { CalendarCommonRenderer } from "@web/views/calendar";

import { useMandatoryDays } from '../../hooks.js';
import { TimeOffCalendarCommonPopover } from './calendar_common_popover.js';


export class TimeOffCalendarCommonRenderer extends CalendarCommonRenderer {
    static components = {
        ...TimeOffCalendarCommonRenderer,
        Popover: TimeOffCalendarCommonPopover,
    };
    setup() {
        super.setup();
        this.mandatoryDays = useMandatoryDays(this.props);
        onWillStart(async () => {
            this.isManager = (await user.hasGroup("hr_holidays.group_hr_holidays_user"));
        });
    }

    getDayCellClassNames(info) {
        return [...super.getDayCellClassNames(info), ...this.mandatoryDays(info)];
    }

    onClick(info) {
        // To open record view
        return this.onDblClick(info)
    }
}
