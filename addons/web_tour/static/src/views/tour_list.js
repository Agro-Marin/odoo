/** @odoo-module native */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ListController, listView } from "@web/views/list";

class TourListController extends ListController {
    setup() {
        super.setup();
        this.tourService = useService("tour_service");
    }
}

registry.category("views").add("tour_list", {
    ...listView,
    Controller: TourListController,
    buttonTemplate: "web_tour.TourListController.Buttons",
});
