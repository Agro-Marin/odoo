// @ts-check
/** @odoo-module native */

/** @module @web/components/record_selectors/record_autocomplete */

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

/**
 * The plain quick-search autocomplete behind `RecordSelector` and
 * `MultiRecordSelector`. It shares its search core — call shape, limits,
 * overflow rule, "Search more..." dialog helpers — with `Many2XAutocomplete`
 * (see `@web/components/autocomplete/name_search`), and deliberately stays
 * simple otherwise: no create actions, no empty-search memoization (its
 * hosts are short-lived editors, and stale in-flight searches are aborted
 * instead).
 */
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
     * Feed the display names we already fetched to the name service, so the
     * host selectors render the new selection without a second round-trip.
     *
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
        /** @type {any} */ (this.lastProm)?.abort(true);
        const prom = (this.lastProm = this.search(name, SEARCH_LIMIT + 1));
        let fetched;
        try {
            fetched = this.cleanRecords(await prom);
        } catch (error) {
            if (error instanceof ConnectionAbortedError) {
                return [];
            }
            throw error;
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
     * @returns {Promise<Array<Record<string, any>>>} the server's matches;
     *  the promise keeps the ORM's `abort()`
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
     * Multi-line display names are cut to their first line, nameless records
     * labelled.
     *
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
