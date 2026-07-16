/** @odoo-module native */
import { onWillStart } from "@odoo/owl";
import { ProductNameAndDescriptionListRendererMixin } from "@product/product_name_and_description/product_name_and_description";
import { useMovePackageDialog } from "@stock/views/select_packages_dialog";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many/x2many_field";
import { user } from "@web/services/user";
import { ListRenderer } from "@web/views/list/list_renderer";

export class MovesListRenderer extends ListRenderer {
    static rowsTemplate = "stock.AddPackageListRendererRows";

    setup() {
        super.setup();
        this.openPackageDialog = useMovePackageDialog();
        this.descriptionColumn = "description_picking";
        this.productColumns = ["product_id", "product_template_id"];

        onWillStart(async () => {
            this.hasPackageActive = await user.hasGroup("stock.group_tracking_lot");
        });
    }

    async onClickMovePackage() {
        // If picking doesn't exist yet or location is outdated, it will lead to incorrect results
        const canOpenDialog = await this.forceSave();
        if (!canOpenDialog) {
            return;
        }
        this.openPackageDialog(this.pickingId, this.locationId);
    }

    get canAddPackage() {
        return (
            this.hasPackageActive &&
            !["done", "cancel"].includes(this.props.list.context.picking_state) &&
            this.props.list.context.picking_type_code !== "incoming"
        );
    }

    async forceSave() {
        // This means the record hasn't been saved once, but we need the picking id to know for which picking we create the move lines.
        const record = this.env.model.root;
        const result = await record.save();
        this.pickingId = record.data.id;
        this.locationId = record.data.location_id?.id;
        return result;
    }
}

patch(MovesListRenderer.prototype, ProductNameAndDescriptionListRendererMixin());

export class StockMoveX2ManyField extends X2ManyField {
    static components = { ...X2ManyField.components, ListRenderer: MovesListRenderer };
}

export const stockMoveX2ManyField = {
    ...x2ManyField,
    component: StockMoveX2ManyField,
};

registry.category("fields").add("stock_move_one2many", stockMoveX2ManyField);
