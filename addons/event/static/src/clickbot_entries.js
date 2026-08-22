/** @odoo-module native */

import { registry } from "@web/core/registry";

// `web` used to carry this name itself, which put the base of the addon
// graph in the position of knowing a module downstream of it -- and meant a
// rename here silently stopped matching there. The owner declares it, by
// category name, so nothing is imported from web's webclient.
registry
    .category("clickbot_skipped_menus")
    .add("event.menu_event_registration_desk", true);
