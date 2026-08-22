/** @odoo-module native */
import { registry } from "@web/core/registry";

const html_upgrade = registry.category("html_editor_upgrade");

html_upgrade.category("1.0");

html_upgrade
    .category("1.1")
    .add("html_editor", "@html_editor/html_migrations/migration-1.1");

html_upgrade
    .category("1.2")
    .add("html_editor", "@html_editor/html_migrations/migration-1.2");

html_upgrade.category("2.0");
