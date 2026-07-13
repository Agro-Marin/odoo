// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_filter_section/calendar_filter_section - Collapsible sidebar filter section for a calendar filter field (attendees, resources) */

import { Component, onWillRender, useState } from "@odoo/owl";
import { AutoComplete } from "@web/components/autocomplete/autocomplete";
import { Transition } from "@web/components/transition";
import { _t } from "@web/core/l10n/translation";
import { useOwnedDialogs, useService } from "@web/core/utils/hooks";
import { getColor, sortCalendarFilters } from "@web/views/calendar/calendar_utils";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

let nextId = 1;

/** Collapsible sidebar section for a single calendar filter field (e.g. attendees, resources). */
export class CalendarFilterSection extends Component {
    static components = {
        AutoComplete,
        Transition,
    };
    static template = "web.CalendarFilterSection";
    static subTemplates = {
        filter: "web.CalendarFilterSection.filter",
    };
    static props = {
        model: Object,
        section: Object,
    };

    setup() {
        this.state = useState({
            collapsed: false,
            fieldRev: 1,
        });
        this.addDialog = useOwnedDialogs();
        this.orm = useService("orm");

        // Reserve a unique id namespace for this section instance so the input
        // ids it emits never collide with a sibling section's.
        this.filterIdBase = nextId++;
        this.filterIdSeq = 0;
        // Double-click guard for filter removal, cleared in a `finally` so a
        // failed unlink RPC doesn't leave a zombie remove button.
        this.unlinkingFilterIds = new Set();
        // Reset the per-render sequence before every render: a given template
        // position then always yields the same id, so element ids stay stable
        // across re-renders instead of churning on each eval (nextFilterId used
        // to bump a module-global, changing every id on every render).
        onWillRender(() => {
            this.filterIdSeq = 0;
        });
    }

    get autoCompleteProps() {
        return {
            autoSelect: true,
            resetOnSelect: true,
            placeholder: _t("+ Add %s", this.section.label),
            sources: [
                {
                    placeholder: _t("Loading..."),
                    options: (request) => this.loadSource(request),
                    optionSlot: "option",
                },
            ],
            value: "",
            class: "mt-1",
        };
    }

    get isAllActive() {
        return (
            this.section.filters.length &&
            this.section.filters.every((filter) => filter.active)
        );
    }

    get nextFilterId() {
        this.filterIdSeq += 1;
        return `${this.filterIdBase}_${this.filterIdSeq}`;
    }

    get section() {
        return this.props.section;
    }

    getFilterColor(filter) {
        return filter.colorIndex !== null
            ? `o_cw_filter_color_${getColor(filter.colorIndex)}`
            : "";
    }

    /** @returns {Object[]} filters sorted by type priority (user, record, dynamic) then label */
    getSortedFilters() {
        return sortCalendarFilters(this.section.filters, ["user", "record", "dynamic"]);
    }

    /**
     * Search for matching records to populate the autocomplete dropdown.
     *
     * @param {string} request - user search input text
     * @returns {Promise<Object[]>} autocomplete option objects
     */
    async loadSource(request) {
        const resModel = this.props.model.fields[this.section.fieldName].relation;
        const activeIds = this.section.filters.map((f) => f.value);
        const domain = [["id", "not in", activeIds]];
        const records = await this.orm.call(resModel, "name_search", [], {
            name: request,
            operator: "ilike",
            domain: domain,
            limit: 8,
            context: this.section.context,
        });

        const options = records.map((result) => ({
            data: {
                id: result[0],
            },
            label: result[1],
            onSelect: () =>
                this.props.model.createFilter(this.section.fieldName, result[0]),
        }));

        if (records.length > 7) {
            options.push({
                cssClass: "o_calendar_dropdown_option",
                label: _t("Search More..."),
                onSelect: () => this.onSearchMore(resModel, domain, request),
            });
        }

        if (!records.length) {
            options.push({
                cssClass: "o_m2o_no_result",
                label: _t("No records"),
            });
        }

        return options;
    }

    toggleSection() {
        this.state.collapsed = !this.state.collapsed;
    }

    onFilterInputChange(filter, ev) {
        this.props.model.updateFilters(
            this.section.fieldName,
            [filter],
            ev.target.checked,
        );
        this.render();
    }

    onAllFilterInputChange(ev) {
        const { fieldName, filters } = this.section;
        this.props.model.updateFilters(fieldName, filters, ev.target.checked);
        this.render();
    }

    onFilterRemoveBtnClick(filter) {
        if (this.unlinkingFilterIds.has(filter.recordId)) {
            return;
        }
        this.unlinkingFilterIds.add(filter.recordId);
        Promise.resolve(
            this.props.model.unlinkFilter(this.section.fieldName, filter.recordId),
        ).finally(() => this.unlinkingFilterIds.delete(filter.recordId));
        this.render();
    }

    async onSearchMore(resModel, domain, request) {
        const dynamicFilters = [];
        if (request.length) {
            const nameGets = await this.orm.call(resModel, "name_search", [], {
                name: request,
                domain: domain,
                operator: "ilike",
                context: this.section.context,
            });
            dynamicFilters.push({
                description: _t("Quick search: %s", request),
                domain: [["id", "in", nameGets.map((nameGet) => nameGet[0])]],
            });
        }
        this.addDialog(SelectCreateDialog, {
            title: _t("Search: %s", this.section.label),
            noCreate: true,
            multiSelect: true,
            resModel,
            context: this.section.context,
            domain,
            onSelected: (resId) =>
                this.props.model.createFilter(this.section.fieldName, resId),
            dynamicFilters,
        });
    }
}
