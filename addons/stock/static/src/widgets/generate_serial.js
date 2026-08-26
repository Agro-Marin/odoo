/** @odoo-module native */
import { Component, onWillStart, useState } from "@odoo/owl";
import { useOperationGuard } from "@stock/utils/use_operation_guard";
import { x2ManyCommands } from "@web/core/network";
import { parseFloat as parseFloatLocale, parseInteger } from "@web/core/parsers";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { Dialog } from "@web/ui/dialog";
import { standardWidgetProps } from "@web/views/widgets";

/**
 * Parse a quantity the user typed, in the user's own locale.
 *
 * These were `<input type="number">`, which is the anomaly here: every numeric
 * field the framework renders is a text input parsed through
 * `@web/core/parsers`. The DOM normalises a `type="number"` value to the HTML
 * *valid floating-point number* form -- period decimal separator -- whatever the
 * locale, which made both parser families wrong in opposite directions: the
 * locale-aware ones read the normalised "2.5" as 25 wherever "." groups
 * thousands, and the global ones cannot read a comma decimal at all. Reading a
 * text input in the user's locale removes the mismatch instead of picking a side
 * of it, and lets a comma-decimal locale type "2,5" and mean it.
 *
 * `parseInteger` rejects a fraction by throwing; that throw used to escape the
 * click handler, so it is turned into a message here.
 *
 * @param {string} raw
 * @param {{ integer?: boolean }} [options]
 * @returns {{ value: number, error: string | null }}
 */
export function parseNumberInput(raw, { integer = false } = {}) {
    const trimmed = String(raw ?? "").trim();
    if (!trimmed) {
        return { value: 0, error: null };
    }
    try {
        return {
            value: integer ? parseInteger(trimmed) : parseFloatLocale(trimmed),
            error: null,
        };
    } catch {
        return {
            value: 0,
            error: integer
                ? _t("“%s” is not a whole number.", trimmed)
                : _t("“%s” is not a number.", trimmed),
        };
    }
}

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
        this.title = this._buildTitle();
        this.orm = useService("orm");
        this.opGuard = useOperationGuard();
        this._onGenerate = this.opGuard.guard(this._onGenerate.bind(this));
        // Guarded as well as debounced: `_onGenerate` refuses an empty
        // `nextSerial`, so a click landing while the preview is in flight was
        // told to enter a first number the request was about to supply.
        this.onGenerateCustomSerial = useDebounced(
            this.opGuard.guard(this._onGenerateCustomSerial.bind(this)),
            500,
            { immediate: true },
        );

        // Every field is state, not a DOM ref read at submit time: the values
        // are the dialog's model, and the validation below has to be reachable
        // without a rendered document.
        const move = this.props.move.data;
        this.state = useState({
            nextSerial: "",
            // Presets applied in `generate` mode only, as the onMounted they
            // replace did. `import` reads its quantities from the pasted text.
            count: this.isGenerating ? String(move.product_uom_qty || 2) : "",
            totalReceived:
                this.isGenerating && this.isLot ? String(move.quantity ?? "") : "",
            lots: "",
            keepLines: false,
            error: null,
        });

        onWillStart(async () => {
            this.displayUOM = await user.hasGroup("uom.group_uom");
        });
    }

    get isLot() {
        return this.props.move.data.has_tracking === "lot";
    }

    get isGenerating() {
        return this.props.mode === "generate";
    }

    get busy() {
        return this.opGuard.busy;
    }

    _buildTitle() {
        if (this.props.mode === "generate") {
            return this.isLot
                ? _t("Generate Lot numbers")
                : _t("Generate Serial numbers");
        }
        return this.isLot ? _t("Import Lots") : _t("Import Serials");
    }

    async _onGenerateCustomSerial() {
        const preview = await this.orm.call("product.product", "preview_next_lot", [
            [this.props.move.data.product_id.id],
        ]);
        if (preview) {
            this.state.nextSerial = preview;
        }
    }

    /**
     * Validate the form and return the numbers to generate with, or null with
     * `state.error` set. Split out from `_onGenerate` so the branch matrix
     * (lot/serial x generate/import) is reachable without a DOM.
     *
     * @returns {{ count: number, qtyToProcess: number } | null}
     */
    _validate() {
        const move = this.props.move.data;
        if (this.isGenerating && !this.state.nextSerial.trim()) {
            this.state.error = this.isLot
                ? _t("Enter the first lot number.")
                : _t("Enter the first serial number.");
            return null;
        }
        if (!this.isGenerating && !this.state.lots.trim()) {
            this.state.error = _t("Enter at least one lot or serial number.");
            return null;
        }

        const count = parseNumberInput(this.state.count, { integer: !this.isLot });
        if (count.error) {
            this.state.error = count.error;
            return null;
        }
        if (this.isGenerating && !this.isLot && !(count.value >= 1)) {
            this.state.error = _t("Generate at least one serial number.");
            return null;
        }

        let qtyToProcess = move.product_qty;
        if (this.isLot) {
            const received = parseNumberInput(this.state.totalReceived);
            if (received.error) {
                this.state.error = received.error;
                return null;
            }
            if (String(this.state.totalReceived).trim()) {
                qtyToProcess = received.value;
            }
        }

        this.state.error = null;
        return { count: count.value, qtyToProcess };
    }

    async _onGenerate() {
        const validated = this._validate();
        if (!validated) {
            return;
        }
        await this._generate(validated.count, validated.qtyToProcess);
        this.props.close();
    }

    async _generate(count, qtyToProcess) {
        const move = this.props.move.data;
        const lines = move.move_line_ids;
        // Decided BEFORE the server is asked where to put the new lines: those
        // lines still occupy their destinations as far as the database is
        // concerned, so putaway would count capacity they are about to give
        // back. `action_generate_lot_line_vals` takes `exclude_sml_ids` for
        // exactly this, and threads it into the putaway count per location.
        const replacedIds = this.state.keepLines ? [] : [...lines.currentIds];
        const move_line_vals = await this.orm.call(
            "stock.move",
            "action_generate_lot_line_vals",
            [
                {
                    ...this.props.move.context,
                    default_product_id: move.product_id.id,
                    default_location_dest_id: move.location_dest_id.id,
                    default_location_id: move.location_id.id,
                    default_tracking: move.has_tracking,
                    default_quantity: qtyToProcess,
                    default_uom_id: this.isLot ? move.product_uom_id?.id : undefined,
                    exclude_sml_ids: replacedIds,
                },
                this.props.mode,
                this.state.nextSerial,
                count,
                this.state.lots,
            ],
        );

        const commands = replacedIds.map((currentId) =>
            x2ManyCommands.delete(currentId),
        );
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
