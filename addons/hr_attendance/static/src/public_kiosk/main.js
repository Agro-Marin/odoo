/** @odoo-module native */
import { createPublicKioskAttendance } from "@hr_attendance/public_kiosk/public_kiosk_app";

if (odoo.__kiosk_backend_info__) {
    createPublicKioskAttendance(document, odoo.__kiosk_backend_info__);
}
