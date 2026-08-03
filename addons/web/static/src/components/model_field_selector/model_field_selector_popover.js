// @ts-check
/** @odoo-module native */

/** @module @web/components/model_field_selector/model_field_selector_popover */

import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { sortBy } from "@web/core/utils/collections/arrays";
import { KeepLast } from "@web/core/utils/concurrency";
import { uniqueId } from "@web/core/utils/functions";
import { useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { useDebounced } from "@web/core/utils/timing";
class Page {
    /**
     * @param {string} resModel
     * @param {Record<string, Object>} fieldDefs
     * @param {Object} [options]
     * @param {Page | null} [options.previousPage]
     * @param {string | null} [options.selectedName]
     * @param {boolean} [options.isDebugMode]
     * @param {boolean} [options.readProperty]
     * @param {(fieldDefs: Record<string, Object>) => string[]} [options.sortFn]
     */
    constructor(resModel, fieldDefs, options = {}) {
        this.resModel = resModel;
        this.fieldDefs = fieldDefs;
        const {
            previousPage = null,
            selectedName = null,
            isDebugMode,
            readProperty = false,
            sortFn = (fieldDefs) =>
                sortBy(Object.keys(fieldDefs), (key) => fieldDefs[key].string),
        } = options;
        this.previousPage = previousPage;
        this.selectedName = selectedName;
        this.isDebugMode = isDebugMode;
        this.readProperty = readProperty;
        this.sortedFieldNames = sortFn(fieldDefs);
        this.fieldNames = this.sortedFieldNames;
        this.query = "";
        this.focusedFieldName = null;
        this.resetFocusedFieldName();
    }

    /** @returns {string} */
    get path() {
        const previousPath = this.previousPage?.path || "";
        const name = this.selectedName;

        if (this.readProperty && this.selectedField && this.selectedField.is_property) {
            if (this.selectedField.relation) {
                return `${previousPath}.get(${JSON.stringify(name)}, env['${this.selectedField.relation}'])`;
            }
            return `${previousPath}.get(${JSON.stringify(name)})`;
        }
        if (name) {
            if (previousPath) {
                return `${previousPath}.${name}`;
            }
            return name;
        }
        return previousPath;
    }

    /** @returns {Object | undefined} */
    get selectedField() {
        return this.fieldDefs[this.selectedName];
    }

    /** @returns {string} */
    get title() {
        const prefix = this.previousPage?.previousPage ? "... > " : "";
        const title = this.previousPage?.selectedField?.string || "";
        if (prefix.length || title.length) {
            return `${prefix}${title}`;
        }
        return _t("Select a field");
    }

    /**
     * @param {"previous" | "next"} direction
     */
    focus(direction) {
        if (!this.fieldNames.length) {
            return;
        }
        const index = this.fieldNames.indexOf(this.focusedFieldName);
        if (direction === "previous") {
            if (index === 0) {
                this.focusedFieldName = this.fieldNames.at(-1);
            } else {
                this.focusedFieldName = this.fieldNames[index - 1];
            }
        } else {
            if (index === this.fieldNames.length - 1) {
                this.focusedFieldName = this.fieldNames[0];
            } else {
                this.focusedFieldName = this.fieldNames[index + 1];
            }
        }
    }

    resetFocusedFieldName() {
        if (this.selectedName && this.fieldNames.includes(this.selectedName)) {
            this.focusedFieldName = this.selectedName;
        } else {
            this.focusedFieldName = this.fieldNames.length ? this.fieldNames[0] : null;
        }
    }

    /**
     * @param {string} [query]
     */
    searchFields(query = "") {
        this.query = query;
        this.fieldNames = this.sortedFieldNames;
        if (query) {
            this.fieldNames = fuzzyLookup(query, this.fieldNames, (key) => {
                const vals = [this.fieldDefs[key].string];
                if (this.isDebugMode) {
                    vals.push(key);
                }
                return vals;
            });
        }
        this.resetFocusedFieldName();
    }
}

export class ModelFieldSelectorPopover extends Component {
    static template = "web.ModelFieldSelectorPopover";
    static props = {
        close: Function,
        filter: { type: Function, optional: true },
        sort: { type: Function, optional: true },
        followRelations: { type: Boolean, optional: true },
        showDebugInput: { type: Boolean, optional: true },
        isDebugMode: { type: Boolean, optional: true },
        path: { optional: true },
        readProperty: { type: Boolean, optional: true },
        resModel: String,
        showSearchInput: { type: Boolean, optional: true },
        update: Function,
    };
    static defaultProps = {
        filter: (value) =>
            value.searchable && value.type !== "json" && value.type !== "separator",
        isDebugMode: false,
        followRelations: true,
    };

    setup() {
        this.fieldService = useService("field");
        this.state = useState({ page: null });
        this.keepLast = new KeepLast();
        this.popoverId = uniqueId("o_model_field_selector_popover_");
        this.hasPendingSearch = false;
        this.debouncedSearchFields = useDebounced(this.searchFields, 250);

        onWillStart(async () => {
            this.state.page = await this.loadPages(
                this.props.resModel,
                this.props.path,
            );
        });

        const rootRef = useRef("root");
        useEffect(
            () => {
                const focusedElement = rootRef.el?.querySelector(
                    ".o_model_field_selector_popover_item.active",
                );
                if (focusedElement) {
                    focusedElement.scrollIntoView({ block: "center" });
                }
            },
            () => [this.state.page, this.state.page?.focusedFieldName],
        );
        useEffect(
            () => {
                if (this.props.showSearchInput) {
                    const searchInput = rootRef.el.querySelector(
                        ".o_model_field_selector_popover_search .o_input",
                    );
                    searchInput.focus();
                }
            },
            () => [this.state.page],
        );
    }

    get fieldNames() {
        return this.state.page.fieldNames;
    }

    /** @returns {string} */
    get listboxId() {
        return `${this.popoverId}_listbox`;
    }

    /**
     * @param {number} index
     * @returns {string}
     */
    getItemId(index) {
        return `${this.popoverId}_${index}`;
    }

    /** @returns {string | undefined} the id of the item the arrow keys are on */
    get focusedItemId() {
        const index = this.fieldNames.indexOf(this.state.page.focusedFieldName);
        return index === -1 ? undefined : this.getItemId(index);
    }

    /**
     * @param {string} query
     */
    onSearchInput(query) {
        this.hasPendingSearch = true;
        this.debouncedSearchFields(query);
    }

    /**
     * Applies a query still sitting in the debounce. Every consumer of the
     * result list goes through this: `focusedFieldName` is derived from the
     * query, so a keyboard action taken before the debounce fires would
     * otherwise commit the field that answered the *previous* query.
     *
     * @returns {boolean} whether a query was waiting -- i.e. whether the list
     *  the caller is about to act on only just came into being. Applying one
     *  parks the focus on its first result, so an arrow that would step
     *  *forwards* from there has already arrived and must not move again.
     */
    flushPendingSearch() {
        const wasPending = this.hasPendingSearch;
        this.debouncedSearchFields.cancel(true);
        return wasPending;
    }

    /**
     * Drops a query typed for a page that is being left. It was never applied,
     * and the field names it would filter belong to another model.
     */
    dropPendingSearch() {
        this.hasPendingSearch = false;
        this.debouncedSearchFields.cancel();
    }

    get showDebugInput() {
        return this.props.showDebugInput ?? this.props.isDebugMode;
    }

    /**
     * @param {Object} fieldDef
     * @returns {boolean | string}
     */
    canFollowRelationFor(fieldDef) {
        if (fieldDef.type === "properties") {
            return true;
        }
        if (!this.props.followRelations) {
            return false;
        }
        return fieldDef.relation;
    }

    /**
     * @param {Record<string, Object>} fieldDefs
     * @param {string} path
     * @param {string} resModel
     * @returns {Record<string, Object>}
     */
    filter(fieldDefs, path, resModel) {
        const filteredKeys = Object.keys(fieldDefs).filter((k) =>
            this.props.filter(fieldDefs[k], path, resModel),
        );
        return Object.fromEntries(filteredKeys.map((k) => [k, fieldDefs[k]]));
    }

    /**
     * @param {Object} fieldDef
     * @returns {Promise<void>}
     */
    async followRelation(fieldDef) {
        this.dropPendingSearch();
        const { modelsInfo } = await this.keepLast.add(
            this.fieldService.loadPath(
                fieldDef.is_property ? fieldDef.relation : this.state.page.resModel,
                `${fieldDef.name}.*`,
            ),
        );
        this.state.page.selectedName = fieldDef.name;
        const { resModel, fieldDefs } = modelsInfo.at(-1);
        this.openPage(
            new Page(resModel, this.filter(fieldDefs, this.state.page.path, resModel), {
                previousPage: this.state.page,
                isDebugMode: this.props.isDebugMode,
                readProperty: this.props.readProperty,
                sortFn: this.props.sort,
            }),
        );
    }

    goToPreviousPage() {
        this.keepLast.cancel();
        this.openPage(this.state.page.previousPage);
    }

    /**
     * @param {string} path
     * @returns {Promise<void>}
     */
    async loadNewPath(path) {
        this.dropPendingSearch();
        const newPage = await this.keepLast.add(
            this.loadPages(this.props.resModel, path),
        );
        this.openPage(newPage);
    }

    /**
     * @param {string} resModel
     * @param {string} [path]
     * @returns {Promise<Page>}
     */
    async loadPages(resModel, path) {
        if (typeof path !== "string" || !path.length) {
            const fieldDefs = await this.fieldService.loadFields(resModel);
            return new Page(resModel, this.filter(fieldDefs, path, resModel), {
                isDebugMode: this.props.isDebugMode,
                readProperty: this.props.readProperty,
                sortFn: this.props.sort,
            });
        }
        const { isInvalid, modelsInfo, names } = await this.fieldService.loadPath(
            resModel,
            path,
        );
        switch (isInvalid) {
            case "model":
                throw new Error(`Invalid model name: ${resModel}`);
            case "path": {
                const { resModel, fieldDefs } = modelsInfo[0];
                return new Page(resModel, this.filter(fieldDefs, path, resModel), {
                    selectedName: path,
                    isDebugMode: this.props.isDebugMode,
                    readProperty: this.props.readProperty,
                    sortFn: this.props.sort,
                });
            }
            default: {
                let page = null;
                for (let index = 0; index < names.length; index++) {
                    const name = names[index];
                    const { resModel, fieldDefs } = modelsInfo[index];
                    page = new Page(resModel, this.filter(fieldDefs, path, resModel), {
                        previousPage: page,
                        selectedName: name,
                        isDebugMode: this.props.isDebugMode,
                        readProperty: this.props.readProperty,
                        sortFn: this.props.sort,
                    });
                }
                return page;
            }
        }
    }

    /**
     * @param {Page} page
     */
    openPage(page) {
        this.dropPendingSearch();
        this.state.page = page;
        this.state.page.searchFields();
        this.props.update(page.path);
    }

    /**
     * @param {string} [query]
     */
    searchFields(query) {
        this.hasPendingSearch = false;
        this.state.page.searchFields(query);
    }

    /**
     * @param {Object} field
     */
    selectField(field) {
        if (field.type === "properties") {
            return this.followRelation(field);
        }
        this.keepLast.cancel();
        this.state.page.selectedName = field.name;
        this.props.update(this.state.page.path, field);
        this.props.close(true);
    }

    /**
     * @param {KeyboardEvent} ev
     */
    onDebugInputKeydown(ev) {
        switch (ev.key) {
            case "Enter": {
                ev.preventDefault();
                ev.stopPropagation();
                this.loadNewPath(
                    /** @type {HTMLInputElement} */ (ev.currentTarget).value,
                );
                break;
            }
        }
    }

    /**
     * @param {KeyboardEvent} ev
     * @returns {Promise<void>}
     */
    async onInputKeydown(ev) {
        const { page } = this.state;
        const target = /** @type {HTMLInputElement} */ (ev.target);
        if (ev.key === "Escape") {
            ev.preventDefault();
            ev.stopPropagation();
            this.props.close();
            return;
        }
        if (!target.closest(".o_model_field_selector_popover_search")) {
            return;
        }
        let justSearched = false;
        if (["ArrowUp", "ArrowDown", "ArrowRight", "Enter"].includes(ev.key)) {
            justSearched = this.flushPendingSearch();
        }
        switch (ev.key) {
            case "ArrowUp": {
                // No special case for a fresh search: the results park the
                // focus on the first of them, and stepping backwards from
                // there wraps onto the last -- which is the end an upward
                // arrow should enter the list from anyway.
                if (target.selectionStart === 0) {
                    page.focus("previous");
                }
                break;
            }
            case "ArrowDown": {
                if (target.selectionStart === target.value.length && !justSearched) {
                    page.focus("next");
                }
                break;
            }
            case "ArrowLeft": {
                if (target.selectionStart === 0 && page.previousPage) {
                    this.goToPreviousPage();
                }
                break;
            }
            case "ArrowRight": {
                if (target.selectionStart === target.value.length) {
                    const focusedFieldName = this.state.page.focusedFieldName;
                    if (focusedFieldName) {
                        const fieldDef = this.state.page.fieldDefs[focusedFieldName];
                        if (this.canFollowRelationFor(fieldDef)) {
                            this.followRelation(fieldDef);
                        }
                    }
                }
                break;
            }
            case "Enter": {
                ev.preventDefault();
                ev.stopPropagation();
                const focusedFieldName = this.state.page.focusedFieldName;
                if (focusedFieldName) {
                    const fieldDef = this.state.page.fieldDefs[focusedFieldName];
                    this.selectField(fieldDef);
                }
                break;
            }
        }
    }
}
