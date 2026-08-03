/** @odoo-module native */
import { onWillStart,useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { CalendarFilterSection } from "@web/views/calendar";

import { TimeOffCardMobile } from "../../../dashboard/time_off_card.js";

export class TimeOffCalendarFilterSection extends CalendarFilterSection {
    static components = {
        ...CalendarFilterSection.components,
        TimeOffCardMobile,
    };
    static subTemplates = {
        filter: "hr_holidays.CalendarFilterSection.filter",
    };

    setup() {
        super.setup();

        this.orm = useService("orm");
        this.leaveState = useState({
            holidays: [],
        });
        onWillStart(this.loadFilterData);
    }

    async loadFilterData() {
        if (!this.env.isSmall || this.section.fieldName !== "holiday_status_id") {
            return;
        }
        const filterData = {};
        const data = await this.orm.call("hr.leave.type", "get_allocation_data_request", []);
        data.forEach((leave) => {
            filterData[leave[3]] = leave;
        });
        this.leaveState.holidays = filterData;
    }
}
