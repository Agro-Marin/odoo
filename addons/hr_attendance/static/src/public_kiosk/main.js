/** @odoo-module native */
import { createPublicKioskAttendance } from "@hr_attendance/public_kiosk/public_kiosk_app";

// Boot entry of the ``hr_attendance.assets_public_attendance`` bundle: the
// kiosk page template inlines ``odoo.__kiosk_backend_info__`` (a classic
// script, executed while the document parses) and this module -- evaluated
// with the bundle, after parsing -- mounts the app from it.
// ``createPublicKioskAttendance`` awaits ``whenReady()`` itself.
//
// The data global doubles as the boot gate: other pages that import this
// module's namespace (e.g. the hoot unit-test runner pulling in
// ``@hr_attendance/*``) never define it and must not start the app.
if (odoo.__kiosk_backend_info__) {
    createPublicKioskAttendance(document, odoo.__kiosk_backend_info__);
}
