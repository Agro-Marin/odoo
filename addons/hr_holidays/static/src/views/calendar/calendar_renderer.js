/** @odoo-module native */
import { CalendarRenderer } from '@web/views/calendar/calendar_renderer';

import { TimeOffCalendarCommonRenderer } from './common/calendar_common_renderer.js';
import { TimeOffCalendarYearRenderer } from './year/calendar_year_renderer.js';

import { TimeOffDashboard } from '../../dashboard/time_off_dashboard.js';

export class TimeOffCalendarRenderer extends CalendarRenderer {
    static template = "hr_holidays.CalendarRenderer";
    static components = {
        ...TimeOffCalendarRenderer.components,
        day: TimeOffCalendarCommonRenderer,
        week: TimeOffCalendarCommonRenderer,
        month: TimeOffCalendarCommonRenderer,
        year: TimeOffCalendarYearRenderer,
        TimeOffDashboard,
    };
    get employeeId() {
        return this.props.model.employeeId;
    }

    get showDashboard() {
        return false;
    }
}

export class TimeOffDashboardCalendarRenderer extends TimeOffCalendarRenderer {
    get showDashboard() {
        return !this.env.isSmall;
    }
}
