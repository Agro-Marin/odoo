import { mailModels } from "@mail/../tests/mail_test_helpers";
import { registerMailMockRoutes } from "@mail/../tests/mock_server/mail_mock_server";
import { defineModels } from "@web/../tests/web_test_helpers";

import { defineAppointmentMockServer } from "./booking/appointment_mock_server.js";
import { CalendarAttendee } from "./mock_server/mock_models/calendar_attendee.js";
import { CalendarEvent } from "./mock_server/mock_models/calendar_event.js";
import { CalendarFilters } from "./mock_server/mock_models/calendar_filters.js";
import { MailActivity } from "./mock_server/mock_models/mail_activity.js";
import { ResUsers } from "./mock_server/mock_models/res_users.js";

export function defineCalendarModels() {
    registerMailMockRoutes();
    defineAppointmentMockServer();
    return defineModels({
        ...mailModels,
        CalendarAttendee,
        CalendarEvent,
        CalendarFilters,
        ResUsers,
        MailActivity,
    });
}
