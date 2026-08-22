/** @odoo-module native */
import { Component, useEffect, useExternalListener, useState } from "@odoo/owl";
import { useAutofocus, useService } from "@web/core/utils/hooks";
/**
 * @prop {{
 * config: {
 * searchFields: Map<string, string>,
 * filter: { show: boolean, options: Map<string, { text: string, indented: boolean? }> }
 * },
 * placeholder: string,
 * }}
 */
export class SearchBar extends Component {
    static template = "point_of_sale.SearchBar";
    static props = {
        config: Object,
        placeholder: String,
        onSearch: Function,
        onFilterSelected: Function,
    };

    setup() {
        this.ui = useService("ui");
        useAutofocus();
        useExternalListener(window, "click", this._hideOptions);
        this.filterOptionsList = [...this.props.config.filter.options.keys()];
        this.searchFieldsList = [...this.props.config.searchFields.keys()];
        const defaultSearchFieldId = this.searchFieldsList.indexOf(
            this.props.config.defaultSearchDetails.fieldName,
        );
        this.state = useState({
            searchInput: this.props.config.defaultSearchDetails.searchTerm || "",
            selectedSearchFieldId:
                defaultSearchFieldId === -1 ? 0 : defaultSearchFieldId,
            showSearchFields: false,
            showFilterOptions: false,
            selectedFilter:
                this.props.config.defaultFilter || this.filterOptionsList[0],
        });
        useEffect(
            () => {
                this.state.selectedFilter =
                    this.props.config.defaultFilter || this.filterOptionsList[0];
            },
            () => [this.props.config.defaultFilter],
        );
    }
    _onSelectFilter(key) {
        this.state.selectedFilter = key;
        this.props.onFilterSelected(this.state.selectedFilter);
    }
    onSearchInputKeydown(event) {
        if (["ArrowUp", "ArrowDown"].includes(event.key)) {
            event.preventDefault();
        }
    }
    onSearchInputKeyup(event) {
        if (["ArrowUp", "ArrowDown"].includes(event.key)) {
            this.state.selectedSearchFieldId = this._fieldIdToSelect(event.key);
        } else if (event.key === "Enter" || this.state.searchInput === "") {
            this._onClickSearchField(
                this.searchFieldsList[this.state.selectedSearchFieldId],
            );
        } else {
            if (
                this.state.selectedSearchFieldId === -1 &&
                this.searchFieldsList.length
            ) {
                this.state.selectedSearchFieldId = 0;
            }
            this.state.showSearchFields = true;
        }
    }
    _onClickSearchField(fieldName) {
        this.state.showSearchFields = false;
        this.props.onSearch({ fieldName, searchTerm: this.state.searchInput });
    }
    /**
     * @param {string} key
     */
    _fieldIdToSelect(key) {
        const length = this.searchFieldsList.length;
        if (!length) {
            return null;
        }
        if (this.state.selectedSearchFieldId === -1) {
            return 0;
        }
        const current = this.state.selectedSearchFieldId || length;
        return (current + (key === "ArrowDown" ? 1 : -1)) % length;
    }
    _hideOptions() {
        this.state.showFilterOptions = false;
        this.state.showSearchFields = false;
    }
}
