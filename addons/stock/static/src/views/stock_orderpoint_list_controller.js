/** @odoo-module native */
import { useOperationGuard } from "@stock/utils/use_operation_guard";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { ListController } from "@web/views/list";

export class StockOrderpointListController extends ListController {
    static template = "stock.StockOrderpoint.listView";

    static components = {
        ...super.components,
        Dropdown,
        DropdownItem,
    };

    setup() {
        super.setup();
        this.opGuard = useOperationGuard();
        this.onClickOrder = this.opGuard.guard(this.onClickOrder.bind(this));
        this.onClickSnooze = this.opGuard.guard(this.onClickSnooze.bind(this));
    }

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
