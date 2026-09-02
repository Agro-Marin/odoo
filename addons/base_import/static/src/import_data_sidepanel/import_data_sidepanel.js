/** @odoo-module native */
import { Component } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox";
import { _t } from "@web/core/translation";
import { DocumentationLink } from "@web/views/widgets";

export class ImportDataSidepanel extends Component {
    static template = "ImportDataSidepanel";
    static components = { CheckBox, DocumentationLink };
    static props = {
        filename: { type: String },
        formattingOptions: { type: Object, optional: true },
        options: { type: Object },
        importTemplates: { type: Array, optional: true },
        isBatched: { type: Boolean, optional: true },
        onOptionChanged: { type: Function },
        onReload: { type: Function },
        hasBinaryFields: { type: Boolean },
        binaryFilesParams: { type: Object },
        onBinaryFilesParamsChanged: { type: Function },
    };

    get fileName() {
        // Split on the LAST dot (mirrors `fileExtension`'s `.pop()` below): a
        // name with an earlier dot, e.g. "2024.orders.csv", used to display
        // as just "2024", silently dropping ".orders" (t24068 tests-finding #10).
        const lastDot = this.props.filename.lastIndexOf(".");
        return lastDot === -1
            ? this.props.filename
            : this.props.filename.slice(0, lastDot);
    }

    get fileExtension() {
        return "." + this.props.filename.split(".").pop();
    }

    getOptionValue(name) {
        if (name === "skip") {
            return (this.props.options.skip + 1).toString();
        }
        return this.props.options[name].toString();
    }

    setOptionValue(name, value) {
        this.props.onOptionChanged(
            name,
            isNaN(parseFloat(value)) ? value : Number(value),
        );
    }

    /**
     * "Start at line" is 1-based; the server's `skip` counts rows to drop.
     *
     * The guard used to be `ev.target.value ? value - 1 : 0`, which is wrong
     * for two of the three things a free-text input can hold. The string "0" is
     * truthy in JavaScript, so entering 0 sent `skip = -1` -- and `data[-1:]` is
     * a perfectly legal Python slice, so the import silently ran on the *last
     * row of the file* and reported success. Any negative entry did the same,
     * further from the end. Non-numeric text sent `NaN`, which JSON-encodes as
     * `null`.
     */
    onLimitChange(ev) {
        const line = Number.parseInt(ev.target.value, 10);
        const skip = Number.isInteger(line) && line > 1 ? line - 1 : 0;
        this._echo(ev.target, skip + 1);
        this.props.onOptionChanged("skip", skip);
    }

    /**
     * Batch size, clamped to at least one row: 0 means "no batching" to the
     * server and a negative value used to index past the start of the row
     * window, raising `IndexError` as an HTTP 500.
     */
    onBatchLimitChange(ev) {
        const limit = Number.parseInt(ev.target.value, 10);
        const clamped = Number.isInteger(limit) && limit > 0 ? limit : 1;
        this._echo(ev.target, clamped);
        this.props.onOptionChanged("limit", clamped);
    }

    /**
     * Show the value that was accepted, not the one that was typed.
     *
     * Both inputs render through `t-att-value`, so when clamping maps the
     * entry back onto the value already held, the vdom attribute does not
     * change and OWL patches nothing -- leaving the box reading "abc" or "0"
     * while the import runs on 1. Writing it back is the only way the field
     * can state what will actually be used.
     */
    _echo(input, value) {
        input.value = value.toString();
    }

    /**
     * Whether a formatting option applies to the file currently loaded.
     *
     * Only the three CSV-parsing options (encoding, separator, text delimiter)
     * are format-specific. The date, datetime and number-separator options are
     * consumed by `_parse_date_from_data` / `_parse_float_from_data`, which run
     * for every reader -- so hiding the whole panel for anything but `.csv`
     * left an xlsx or ods user with no way to correct the server's guess. A
     * spreadsheet holding the text "03/04/2024" is guessed as `%m/%d/%Y`
     * (measured), so a European file imports 3 April as 4 March, silently, and
     * the one control that would fix it was not on screen.
     */
    isOptionApplicable(option) {
        return !option.csvOnly || this.fileExtension.toLowerCase() === ".csv";
    }

    get binaryFilesLabel() {
        const files = this.props.binaryFilesParams.binaryFiles.value;
        const number = Object.keys(files).length;
        if (number > 0) {
            return _t("%(number)s file(s) selected", { number });
        }
        return _t("No file selected");
    }
}
