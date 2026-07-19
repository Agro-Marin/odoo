/** @odoo-module native */
import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { parseInteger } from "@web/fields/parsers";
import { x2ManyCommands } from "@web/model/relational_model/commands";
import { user } from "@web/services/user";
import { Dialog } from "@web/ui/dialog/dialog";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class GenerateDialog extends Component {
    static template = "stock.generate_serial_dialog";
    static components = { Dialog };
    static props = {
        mode: { type: String },
        move: { type: Object },
        close: { type: Function },
    };
    setup() {
        this.size = "md";
        if (this.props.mode === "generate") {
            this.title =
                this.props.move.data.has_tracking === "lot"
                    ? _t("Generate Lot numbers")
                    : _t("Generate Serial numbers");
        } else {
            this.title =
                this.props.move.data.has_tracking === "lot"
                    ? _t("Import Lots")
                    : _t("Import Serials");
        }

        this.nextSerial = useRef("nextSerial");
        this.nextSerialCount = useRef("nextSerialCount");
        this.totalReceived = useRef("totalReceived");
        this.keepLines = useRef("keepLines");
        this.lots = useRef("lots");
        this.orm = useService("orm");
        // In-flight guard: Generate runs an RPC + command batch; a second click
        // during the await must not emit a second batch (duplicated lines).
        this.state = useState({ busy: false });
        // Debounced (leading edge): rapid repeat clicks on "New" collapse into
        // one preview RPC.
        this.onGenerateCustomSerial = useDebounced(this._onGenerateCustomSerial, 500, {
            immediate: true,
        });
        onWillStart(async () => {
            this.displayUOM = await user.hasGroup("uom.group_uom");
        });
        onMounted(() => {
            if (this.props.mode === "generate") {
                this.nextSerialCount.el.value =
                    this.props.move.data.product_uom_qty || 2;
                if (this.props.move.data.has_tracking === "lot") {
                    this.totalReceived.el.value = this.props.move.data.quantity;
                }
            }
        });
    }
    async _onGenerateCustomSerial() {
        // Single read-only RPC: the server interpolates legends and pads the
        // number without consuming the sequence, so previewing (or discarding
        // the dialog) never burns a number.
        const preview = await this.orm.call("product.product", "preview_next_lot", [
            [this.props.move.data.product_id.id],
        ]);
        if (preview) {
            this.nextSerial.el.value = preview;
        }
    }
    async _onGenerate() {
        if (this.state.busy) {
            return;
        }
        let count;
        let qtyToProcess;
        if (this.props.move.data.has_tracking === "lot") {
            count = parseFloat(this.nextSerialCount.el?.value || "0");
            qtyToProcess = parseFloat(
                this.totalReceived.el?.value || this.props.move.data.product_qty,
            );
        } else {
            count = parseInteger(this.nextSerialCount.el?.value || "0");
            qtyToProcess = this.props.move.data.product_qty;
        }
        // Validate BEFORE building any command: an empty submit must not wipe
        // the existing lines ("keep current lines" unchecked deletes them all
        // even when nothing is generated).
        if (this.props.mode === "generate") {
            if (!this.nextSerial.el?.value.trim()) {
                return;
            }
            // Serial mode: a non-positive count generates nothing.
            // NB: `!(count >= 1)` also rejects NaN.
            if (this.props.move.data.has_tracking !== "lot" && !(count >= 1)) {
                return;
            }
        } else if (!this.lots.el?.value.trim()) {
            return;
        }
        this.state.busy = true;
        try {
            await this._generate(count, qtyToProcess);
            this.props.close();
        } finally {
            this.state.busy = false;
        }
    }
    async _generate(count, qtyToProcess) {
        const move_line_vals = await this.orm.call(
            "stock.move",
            "action_generate_lot_line_vals",
            [
                {
                    ...this.props.move.context,
                    default_product_id: this.props.move.data.product_id.id,
                    default_location_dest_id: this.props.move.data.location_dest_id.id,
                    default_location_id: this.props.move.data.location_id.id,
                    default_tracking: this.props.move.data.has_tracking,
                    default_quantity: qtyToProcess,
                    default_uom_id:
                        this.props.move.data.has_tracking === "lot"
                            ? this.props.move.data.product_uom_id?.id
                            : undefined,
                },
                this.props.mode,
                this.nextSerial.el?.value,
                count,
                this.lots.el?.value,
            ],
        );
        const lines = this.props.move.data.move_line_ids;

        // Create the generated lines directly from the server-computed values.
        // The CREATE command bypasses onchanges (as intended here); using the
        // public applyCommands lets the model handle datapoint creation, command
        // tracking, currentIds, count/limit and the update notification — instead
        // of poking private internals by hand. Clear the existing lines first
        // unless "keep current lines" is ticked.
        const commands = [];
        if (!this.keepLines.el.checked) {
            commands.push(
                ...lines.currentIds.map((currentId) =>
                    x2ManyCommands.delete(currentId),
                ),
            );
        }
        for (const values of move_line_vals) {
            commands.push(x2ManyCommands.create(false, values));
        }
        await lines.applyCommands(commands);
    }
}

class GenerateSerials extends Component {
    static template = "stock.GenerateSerials";
    static props = { ...standardWidgetProps };

    setup() {
        this.dialog = useService("dialog");
    }

    openDialog() {
        this.dialog.add(GenerateDialog, {
            move: this.props.record,
            mode: "generate",
        });
    }
}

class ImportLots extends Component {
    static template = "stock.ImportLots";
    static props = { ...standardWidgetProps };
    setup() {
        this.dialog = useService("dialog");
    }

    openDialog() {
        this.dialog.add(GenerateDialog, {
            move: this.props.record,
            mode: "import",
        });
    }
}
registry.category("view_widgets").add("import_lots", { component: ImportLots });
registry
    .category("view_widgets")
    .add("generate_serials", { component: GenerateSerials });
