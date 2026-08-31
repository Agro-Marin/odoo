/** @odoo-module native */

import { registry } from "@web/core/registry";

const skipped = registry.category("clickbot_skipped_menus");
skipped.add("hr_attendance.menu_action_view_form", true);
skipped.add("hr_attendance.menu_hr_attendance_onboarding", true);
