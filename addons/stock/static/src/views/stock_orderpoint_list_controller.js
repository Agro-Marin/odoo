/** @odoo-module native */
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { ListController } from "@web/views/list/list_controller";

export class StockOrderpointListController extends ListController {
    static template = "stock.StockOrderpoint.listView";

    static components = {
        ...super.components,
        Dropdown,
        DropdownItem,
    };

    async onClickOrder(force_to_max) {
        const resIds = await this.model.root.getResIds(true);
        const action = await this.model.orm.call(
            this.props.resModel,
            "action_replenish",
            [resIds],
            {
                context: this.props.context,
                force_to_max: force_to_max,
            },
        );
        if (action) {
            await this.actionService.doAction(action);
        }
        // Soft in-place reload instead of a full-webclient `reload` client action:
        // the latter hard-reloads the browser (losing scroll/search facets) and
        // destroys the action_replenish notification — which carries the link to
        // the generated picking — before the user can click it.
        await this.model.load();
    }

    async onClickSnooze() {
        const resIds = await this.model.root.getResIds(true);
        return this.actionService.doAction("stock.action_orderpoint_snooze", {
            additionalContext: { default_orderpoint_ids: resIds },
            onClose: () => this.model.load(),
        });
    }
}
