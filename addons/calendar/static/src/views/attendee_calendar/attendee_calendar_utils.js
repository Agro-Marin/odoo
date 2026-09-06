/** @odoo-module native */

/**
 * Return the CSS class reflecting the current user's attendee status for a
 * calendar record, shared between the day/week/month and year view renderers.
 */
export function getAttendeeStatusClass(record) {
    if (record.isAlone) {
        return "o_attendee_status_alone";
    }
    return `o_attendee_status_${record.attendeeStatus}`;
}
