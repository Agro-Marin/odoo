// @ts-check
/** @odoo-module native */

/** @module @web/components/record_selectors/record_autocomplete */

import { Component } from "@odoo/owl";
import { AutoComplete } from "@web/components/autocomplete/autocomplete";
import { Domain } from "@web/core/domain";
import { ConnectionAbortedError } from "@web/core/network/rpc";
import { getSelectCreateDialog } from "@web/core/record_dialog_port";
import { _t } from "@web/core/translation";
import { useOwnedDialogs, useService } from "@web/core/utils/hooks";
const SEARCH_LIMIT = 7;
const SEARCH_MORE_LIMIT = 320;

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
     * @param {Array<[number, any]>} options
     */
    addNames(options) {
        const displayNames = Object.fromEntries(options);
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
        let records;
        try {
            records = await prom;
        } catch (error) {
            if (error instanceof ConnectionAbortedError) {
                return [];
            }
            throw error;
        }
        const nameGets = records.map(
            ([id, label]) =>
                /** @type {[number, any]} */ ([
                    id,
                    label ? label.split("\n")[0] : _t("Unnamed"),
                ]),
        );
        this.addNames(nameGets);
        /** @type {Array<Record<string, any>>} */
        const options = nameGets.slice(0, SEARCH_LIMIT).map(([id, label]) => ({
            data: {
                record: { id, display_name: label },
            },
            label,
            onSelect: () => this.props.update([id]),
        }));
        if (SEARCH_LIMIT < nameGets.length) {
            options.push({
                cssClass: "o_m2o_dropdown_option",
                label: _t("Search More..."),
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
            const nameGets = await this.search(name, SEARCH_MORE_LIMIT);
            this.addNames(nameGets);
            operator = "in";
            ids.push(...nameGets.map((nameGet) => nameGet[0]));
        } else {
            operator = "not in";
            ids.push(...this.getIds());
        }
        const dynamicFilters = ids.length
            ? [
                  {
                      description: _t("Quick search: %s", name),
                      domain: [["id", operator, ids]],
                  },
              ]
            : undefined;
        const SelectCreateDialog = getSelectCreateDialog();
        let title = _t("Search");
        if (fieldString && fieldString.trim()) {
            title = _t("Search: %s", fieldString);
        }
        this.addDialog(SelectCreateDialog, {
            title,
            dynamicFilters,
            domain: this.getDomain(),
            resModel,
            noCreate: true,
            multiSelect,
            context: this.props.context || {},
            onSelected: (/** @type {number|number[]} */ resId) => {
                const resIds = Array.isArray(resId) ? resId : [resId];
                this.props.update([...resIds]);
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
     * @returns {Promise<Array<[number, string]>>} the server's (id, display_name) pairs
     */
    search(name, limit) {
        const domain = this.getDomain();
        return this.orm.call(this.props.resModel, "name_search", [], {
            name,
            domain: domain,
            limit,
            context: this.props.context || {},
        });
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
