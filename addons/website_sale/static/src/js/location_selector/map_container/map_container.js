/** @odoo-module native */
import { MapContainer } from "@delivery/js/location_selector/map_container/map_container";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/translation";

patch(MapContainer.prototype, {
    get errorMessage() {
        return _t("There was an error loading the map");
    },

    get chooseLocationButtonLabel() {
        return _t("Choose this location");
    },

    get openingHoursLabel() {
        return _t("Opening hours");
    },
});
