import { CalendarEvent } from "./mock_server/mock_models/calendar_event.js";
import { CalendarAttendee } from "./mock_server/mock_models/calendar_attendee.js";
import { ResUsers } from "./mock_server/mock_models/res_users.js";
import { MailActivity } from "./mock_server/mock_models/mail_activity.js";
import { CalendarFilters } from "./mock_server/mock_models/calendar_filters.js";

import { mailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels } from "@web/../tests/web_test_helpers";

export const calendarModels = {
    CalendarAttendee,
    CalendarEvent,
    CalendarFilters,
    ResUsers,
    MailActivity,
};

export function defineCalendarModels() {
    return defineModels({ ...mailModels, ...calendarModels });
}
