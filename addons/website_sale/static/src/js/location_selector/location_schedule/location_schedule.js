/** @odoo-module native */
import { LocationSchedule } from "@delivery/js/location_selector/location_schedule/location_schedule";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/translation";

patch(LocationSchedule.prototype, {
    get closedLabel() {
        return _t("Closed");
    },
});
