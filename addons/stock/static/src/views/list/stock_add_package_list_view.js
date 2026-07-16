/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useMovePackageDialog } from "@stock/views/select_packages_dialog";

export class AddPackageListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.openPackageDialog = useMovePackageDialog();
        this.pickingId = this.props.list.context.picking_ids?.length
            ? this.props.list.context.picking_ids[0]
            : 0;
        this.locationId = this.props.list.context.location_id || 0;
        this.canAddEntirePacks = this.props.list.context?.can_add_entire_packs;
    }

    get displayRowCreates() {
        return this.canAddEntirePacks;
    }

    async add() {
        await this.onClickAdd();
    }

    async onClickAdd() {
        this.openPackageDialog(this.pickingId, this.locationId);
    }
}

registry.category("views").add("stock_add_package_list_view", {
    ...listView,
    Renderer: AddPackageListRenderer,
});
