/** @odoo-module native */
import { Location } from "@delivery/js/location_selector/location/location";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/translation";

patch(Location.prototype, {
    get openingHoursLabel() {
        return _t("Opening hours");
    },
});
