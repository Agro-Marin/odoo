/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";

import { ArchiveDisabledListController } from "./archive_disabled_list_controller.js";

export const archiveDisabledListView = {
    ...listView,
    Controller: ArchiveDisabledListController,
};

registry
    .category("views")
    .add("archive_disabled_activity_list", archiveDisabledListView);
