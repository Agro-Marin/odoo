// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { AutoComplete } from "@web/components/autocomplete/autocomplete";
import {
    normalizeSelectedIds,
    quickSearchFilter,
    SEARCH_LIMIT,
    SEARCH_MORE_LIMIT,
    searchMoreLabel,
    searchMoreTitle,
    splitOverflow,
    webNameSearch,
} from "@web/components/autocomplete/name_search";
import { Domain } from "@web/core/domain";
import { ConnectionAbortedError } from "@web/core/network/rpc";
import { getSelectCreateDialog } from "@web/core/record_dialog_port";
import { _t } from "@web/core/translation";
import { useOwnedDialogs, useService } from "@web/core/utils/hooks";

export class RecordAutocomplete extends Component {
    static props = {
        resModel: String,
        update: Function,
        multiSelect: Boolean,
        getIds: Function,
        value: String,
        domain: { type: Array, optional: true },
        context: { type: Object, optional: true },
        className: { type: String, optional: true },
        fieldString: { type: String, optional: true },
        placeholder: { type: String, optional: true },
        slots: { optional: true },
    };
    static components = { AutoComplete };
    static template = "web.RecordAutocomplete";

    /** @type {ReturnType<typeof useOwnedDialogs>} */
    addDialog;
    /** @type {import("services").ServiceFactories["name"]} */
    nameService;
    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /**
     * @type {any}
     */
    lastProm = null;

    setup() {
        this.orm = useService("orm");
        this.nameService = useService("name");
        this.addDialog = useOwnedDialogs();
        this.sources = [
            {
                placeholder: _t("Loading..."),
                options: this.loadOptionsSource.bind(this),
                optionSlot: this.props.slots?.autoCompleteItem ? "option" : undefined,
            },
        ];
    }

    /**
     * @param {Array<{ id: number, display_name: any }>} records
     */
    addNames(records) {
        const displayNames = Object.fromEntries(
            records.map(({ id, display_name }) => [id, display_name]),
        );
        this.nameService.addDisplayNames(this.props.resModel, displayNames);
    }

    getIds() {
        return this.props.getIds();
    }

    /**
     * @param {string} name
     */
    async loadOptionsSource(name) {
        this.lastProm?.abort(true);
        const prom = (this.lastProm = this.search(name, SEARCH_LIMIT + 1));
        let fetched;
        try {
            fetched = this.cleanRecords(await prom);
        } catch (error) {
            if (error instanceof ConnectionAbortedError) {
                return [];
            }
            throw error;
        } finally {
            if (this.lastProm === prom) {
                this.lastProm = null;
            }
        }
        this.addNames(fetched);
        const { records, hasMore } = splitOverflow(fetched, SEARCH_LIMIT);
        /** @type {Array<Record<string, any>>} */
        const options = records.map((record) => ({
            data: { record },
            label: record.display_name,
            onSelect: () => this.props.update([record.id]),
        }));
        if (hasMore) {
            options.push({
                cssClass: "o_m2o_dropdown_option o_m2o_dropdown_option_search_more",
                label: searchMoreLabel(),
                onSelect: this.onSearchMore.bind(this, name),
            });
        }
        if (!options.length) {
            options.push({ label: _t("(no result)") });
        }
        return options;
    }

    /**
     * @param {string} name
     */
    async onSearchMore(name) {
        const { fieldString, multiSelect, resModel } = this.props;
        let operator;
        const ids = [];
        if (name) {
            const records = this.cleanRecords(
                await this.search(name, SEARCH_MORE_LIMIT),
            );
            this.addNames(records);
            operator = "in";
            ids.push(...records.map((record) => record.id));
        } else {
            operator = "not in";
            ids.push(...this.getIds());
        }
        const dynamicFilters = ids.length
            ? [quickSearchFilter(name, ids, operator)]
            : undefined;
        const SelectCreateDialog = getSelectCreateDialog();
        this.addDialog(SelectCreateDialog, {
            title: searchMoreTitle(fieldString),
            dynamicFilters,
            domain: this.getDomain(),
            resModel,
            noCreate: true,
            multiSelect,
            context: this.props.context || {},
            onSelected: (/** @type {number|number[]} */ resId) => {
                this.props.update(normalizeSelectedIds(resId));
            },
        });
    }

    getDomain() {
        const domainIds = Domain.not([["id", "in", this.getIds()]]);
        if (this.props.domain) {
            return Domain.and([this.props.domain, domainIds]).toList();
        }
        return domainIds.toList();
    }

    /**
     * @param {string} name
     * @param {number} limit
     * @returns {Promise<Array<Record<string, any>>>}
     */
    search(name, limit) {
        return webNameSearch(this.orm, this.props.resModel, {
            name,
            domain: this.getDomain(),
            limit,
            context: this.props.context || {},
        });
    }

    /**
     * @param {Array<Record<string, any>>} records
     * @returns {Array<{ id: number, display_name: any }>}
     */
    cleanRecords(records) {
        return records.map(({ id, display_name }) => ({
            id,
            display_name: display_name ? display_name.split("\n")[0] : _t("Unnamed"),
        }));
    }

    /**
     * @param {{ inputValue: string }} param0
     */
    onChange({ inputValue }) {
        if (!inputValue.length) {
            this.props.update([]);
        }
    }
}
