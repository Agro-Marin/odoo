/** @odoo-module native */

import { attendeeCalendarYearRendererProps } from "@calendar/views/attendee_calendar/year/attendee_calendar_year_renderer";

Object.assign(attendeeCalendarYearRendererProps, {
    openWorkLocationWizard: { type: Function, optional: true },
});
