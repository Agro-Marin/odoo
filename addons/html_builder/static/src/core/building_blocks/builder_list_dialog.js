/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/ui/dialog";
import { fuzzyLookup } from "@web/core/utils/search";

/**
 * Two panels, excluded on the left and included on the right, with one search
 * box over both. It is the answer to a list of records long enough that adding
 * them one at a time from a dropdown stops being reasonable.
 */
export class BuilderListDialog extends Component {
    static template = "html_builder.BuilderListDialog";
    static components = { Dialog };
    static props = {
        excludedRecords: { type: Array },
        includedRecords: { type: Array },
        close: { type: Function },
        save: { type: Function },
    };

    setup() {
        this.state = useState({
            excludedRecords: [...this.props.excludedRecords].sort(this.compareByName),
            includedRecords: [...this.props.includedRecords],
            searchString: "",
        });
    }

    compareByName(a, b) {
        return (a.display_name || "").localeCompare(b.display_name || "");
    }

    search(records) {
        if (!this.state.searchString) {
            return records;
        }
        return fuzzyLookup(this.state.searchString, records, (record) => record.display_name);
    }

    get searchExcluded() {
        return this.search(this.state.excludedRecords);
    }

    get searchIncluded() {
        return this.search(this.state.includedRecords);
    }

    onSearch(ev) {
        this.state.searchString = ev.target.value;
    }

    include(record) {
        const index = this.state.excludedRecords.indexOf(record);
        this.state.includedRecords.push(...this.state.excludedRecords.splice(index, 1));
    }

    exclude(record) {
        const index = this.state.includedRecords.indexOf(record);
        this.state.excludedRecords.push(...this.state.includedRecords.splice(index, 1));
        this.state.excludedRecords.sort(this.compareByName);
    }

    includeAll() {
        this.state.includedRecords.push(...this.state.excludedRecords.splice(0));
    }

    excludeAll() {
        this.state.excludedRecords.push(...this.state.includedRecords.splice(0));
        this.state.excludedRecords.sort(this.compareByName);
    }

    save() {
        this.props.save(this.state.includedRecords);
        this.props.close();
    }
}
