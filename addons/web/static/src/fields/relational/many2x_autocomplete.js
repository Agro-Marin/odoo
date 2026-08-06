// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2x_autocomplete */

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
import { makeContext } from "@web/core/context";
import { RPCError } from "@web/core/network/rpc";
import { getFormViewDialog, getSelectCreateDialog } from "@web/core/record_dialog_port";
import { _t } from "@web/core/translation";
import { KeepLast } from "@web/core/utils/concurrency";
import { highlightText, odoomark } from "@web/core/utils/dom/html";
import {
    useForwardRefToParent,
    useOwnedDialogs,
    useService,
} from "@web/core/utils/hooks";

/**
 * Terms kept per (domain, context) before the memo is dropped. A user cannot
 * type unboundedly many distinct empty searches, but the set is scoped to a
 * long-lived component, so it gets a ceiling.
 */
const EMPTY_SEARCH_MEMO_LIMIT = 64;

/**
 * @param {Object} params
 * @param {string} params.resModel
 * @param {Object} params.activeActions
 * @param {Function} params.onSelected
 * @param {Function} params.onCreateEdit
 * @param {Function} [params.onUnselect]
 * @param {boolean} [params.isToMany]
 * @returns {Function}
 */
export function useSelectCreate({
    resModel,
    activeActions,
    onSelected,
    onCreateEdit,
    onUnselect,
    isToMany,
}) {
    const addDialog = useOwnedDialogs();
    const SelectCreateDialog = getSelectCreateDialog();

    function selectCreate({ domain, context, filters, title }) {
        addDialog(SelectCreateDialog, {
            title: title || _t("Select records"),
            noCreate: !activeActions.create,
            multiSelect:
                isToMany !== undefined
                    ? isToMany && (activeActions.link ?? true)
                    : (activeActions.link ?? false),
            resModel,
            context,
            domain,
            onSelected,
            onCreateEdit: () => onCreateEdit({ context }),
            dynamicFilters: filters,
            onUnselect,
        });
    }
    return selectCreate;
}

export class Many2XAutocomplete extends Component {
    static template = "web.Many2XAutocomplete";
    static components = { AutoComplete };
    static props = {
        activeActions: Object,
        autoSelect: { type: Boolean, optional: true },
        autocomplete_container: { type: Function, optional: true },
        autofocus: { type: Boolean, optional: true },
        context: { type: Object, optional: true },
        createAction: { type: Function, optional: true },
        dropdown: { type: Boolean, optional: true },
        fieldString: String,
        getDomain: Function,
        id: { type: String, optional: true },
        isToMany: { type: Boolean, optional: true },
        nameCreateField: { type: String, optional: true },
        otherSources: { type: Array, optional: true },
        placeholder: { type: String, optional: true },
        quickCreate: { type: [Function, { value: null }], optional: true },
        resModel: String,
        searchLimit: { type: Number, optional: true },
        searchMoreLabel: { type: String, optional: true },
        searchMoreLimit: { type: Number, optional: true },
        searchThreshold: { type: Number, optional: true },
        setInputFloats: { type: Function, optional: true },
        searchMemoization: {
            type: String,
            optional: true,
            validate: (v) => ["none", "exact", "substring"].includes(v),
        },
        slots: { optional: true },
        specification: { type: Object, optional: true },
        update: Function,
        value: { type: String, optional: true },
    };
    static defaultProps = {
        context: {},
        dropdown: true,
        nameCreateField: "name",
        otherSources: [],
        quickCreate: null,
        searchLimit: SEARCH_LIMIT,
        searchMemoization: "exact",
        searchThreshold: 0,
        searchMoreLimit: SEARCH_MORE_LIMIT,
        setInputFloats: () => {},
        specification: {},
        value: "",
    };
    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    autoCompleteContainer;
    /** @type {any} */
    keepLast;
    /** @type {any} */
    selectCreate;
    /**
     * Terms already known to return nothing for the *current* domain/context.
     *
     * Only the last term used to be remembered, so the very next keystroke
     * overwrote it and the memo never fired -- every keystroke past an empty
     * result paid a provably empty RPC.
     *
     * This container is allocated once and only ever mutated in place. The
     * component is reached through more than one reactive proxy, and
     * *reassigning* the field makes a writer and a reader end up on two
     * different objects -- which is why invalidation silently stopped working
     * when this was a plain reassignment.
     *
     * @type {{ signature: string | null, names: Set<string> }}
     */
    emptySearchMemo = { signature: null, names: new Set() };

    setup() {
        this.orm = useService("orm");

        this.autoCompleteContainer = useForwardRefToParent("autocomplete_container");
        const { activeActions, resModel, isToMany, fieldString } = this.props;

        this.keepLast = new KeepLast();

        this.openMany2X =
            this.props.createAction ??
            useOpenMany2XRecord({
                resModel,
                activeActions,
                isToMany,
                onRecordSaved: (record) =>
                    this.update([{ ...record.data, id: record.resId }]),
                onRecordDiscarded: () => {
                    if (!isToMany) {
                        this.update(false);
                    }
                },
                fieldString,
                onClose: () => {
                    this.invalidateEmptySearch();
                    const autoCompleteInput = /** @type {HTMLInputElement | null} */ (
                        this.autoCompleteContainer.el?.querySelector("input")
                    );
                    if (!autoCompleteInput) {
                        return;
                    }

                    if (this.props.value !== autoCompleteInput.value) {
                        autoCompleteInput.value = "";
                    }
                    autoCompleteInput.focus();
                },
                component: this.createDialog,
                size: this.createDialogSize,
            });

        this.selectCreate = useSelectCreate({
            resModel,
            activeActions,
            isToMany,
            onSelected: (resId) => {
                const values = normalizeSelectedIds(resId).map((id) => ({ id }));
                return this.update(values);
            },
            onCreateEdit: ({ context }) => this.openMany2X({ context }),
            onUnselect: isToMany ? undefined : () => this.update(),
        });
    }

    /** @returns {Object} */
    get autoCompleteProps() {
        return {
            autocomplete: "off",
            autoSelect: this.props.autoSelect,
            autofocus: this.props.autofocus,
            dropdown: this.props.dropdown,
            id: this.props.id,
            onCancel: this.onCancel.bind(this),
            onChange: this.onChange.bind(this),
            onInput: this.onInput.bind(this),
            placeholder: this.props.placeholder,
            resetOnSelect: this.props.value === "",
            sources: this.sources,
            slots: this.props.slots,
            value: this.props.value,
        };
    }

    /** @returns {Array<Object>} */
    get sources() {
        return [this.optionsSource, ...this.props.otherSources];
    }

    /** @returns {{ placeholder: string, options: Function, optionSlot: string }} */
    get optionsSource() {
        return {
            placeholder: _t("Loading..."),
            options: this.loadOptionsSource.bind(this),
            optionSlot: "option",
        };
    }

    /** @returns {Object} */
    get activeActions() {
        return this.props.activeActions || {};
    }

    /** @returns {import("@odoo/owl").ComponentConstructor} */
    get createDialog() {
        return getFormViewDialog();
    }

    /** @returns {string} */
    get createDialogSize() {
        return "lg";
    }

    /**
     * @param {string} value
     * @returns {Object}
     */
    getCreationContext(value) {
        return makeContext([
            this.props.context,
            value && { [`default_${this.props.nameCreateField}`]: value },
        ]);
    }
    /** @param {{ inputValue: string }} params */
    onInput({ inputValue }) {
        if (!this.props.value || this.props.value !== inputValue) {
            this.props.setInputFloats(true);
        }
    }
    onCancel() {
        this.props.setInputFloats(false);
    }

    /** @returns {Object} */
    get searchSpecification() {
        return {
            display_name: {},
            ...this.props.specification,
        };
    }

    /**
     * @param {{ name: string, limit: number, domain: any[], context: Object,
     *           specification?: Object }} params
     * @returns {Promise<Array<Object>>}
     */
    nameSearch({ name, limit, domain, context, specification }) {
        return webNameSearch(this.orm, this.props.resModel, {
            name,
            domain,
            limit,
            context,
            specification: specification ?? this.searchSpecification,
        });
    }

    /**
     * @param {string} name
     * @returns {Promise<Array<Object>>}
     */
    async search(name) {
        const domain = this.props.getDomain();
        const context = this.props.context;
        const memo = this.rememberedEmptySearches(domain, context);
        if (memo && this.isKnownEmpty(memo.names, name)) {
            return [];
        }
        const records = await this.nameSearch({
            name,
            limit: this.props.searchLimit + 1,
            domain,
            context,
        });
        if (!records.length && memo) {
            if (memo.names.size >= EMPTY_SEARCH_MEMO_LIMIT) {
                memo.names.clear();
            }
            memo.names.add(name);
        }
        return records;
    }

    /**
     * The memo is scoped to one (domain, context) pair: a change to either can
     * turn a previously empty search into a matching one.
     *
     * @param {any[]} domain
     * @param {Object} context
     * @returns {{ names: Set<string> } | null}
     */
    rememberedEmptySearches(domain, context) {
        if (this.props.searchMemoization === "none") {
            return null;
        }
        const memo = this.emptySearchMemo;
        const signature = JSON.stringify([domain, context]);
        if (memo.signature !== signature) {
            memo.signature = signature;
            memo.names.clear();
        }
        return memo;
    }

    /**
     * `substring` exploits the monotonicity of `ilike '%term%'`: if `%ab%`
     * matched nothing then `%abc%` cannot match either. That only holds for
     * models whose `name_search` is a pure ilike -- `product.product`, for one,
     * ORs in `barcode = term`, so a longer term can match where a shorter one
     * did not. Hence `exact` is the default: it never skips a search that was
     * not literally performed already.
     *
     * @param {Set<string>} names
     * @param {string} name
     * @returns {boolean}
     */
    isKnownEmpty(names, name) {
        if (names.has(name)) {
            return true;
        }
        if (this.props.searchMemoization !== "substring") {
            return false;
        }
        for (const empty of names) {
            if (empty && name.includes(empty)) {
                return true;
            }
        }
        return false;
    }

    invalidateEmptySearch() {
        this.emptySearchMemo.signature = null;
        this.emptySearchMemo.names.clear();
    }

    /**
     * @param {Array<Object>|false} [values]
     * @returns {any}
     */
    update(values) {
        this.invalidateEmptySearch();
        return this.props.update(values);
    }

    /** @param {string} request */
    slowCreate(request) {
        return this.openMany2X({
            context: this.getCreationContext(request),
            nextRecordsContext: this.props.context,
        });
    }

    /**
     * @param {Error} error
     * @param {string} request
     */
    onQuickCreateError(error, request) {
        if (
            error instanceof RPCError &&
            error.exceptionName === "odoo.exceptions.ValidationError"
        ) {
            return this.slowCreate(request);
        } else {
            throw error;
        }
    }

    /**
     * @param {string} request
     * @returns {Promise<Array<Object>>}
     */
    async loadOptionsSource(request) {
        await this.keepLast.add(Promise.resolve());
        return this.suggest(request, (promise) => this.keepLast.add(promise));
    }

    /**
     * @param {string} request
     * @param {Function} lock
     * @returns {Promise<Array<Object>>}
     */
    async suggest(request, lock) {
        const suggestions = [];
        /** @type {Record<string, any>[] | null} */
        let records = null;
        let hasMore = false;

        if (request.length < this.props.searchThreshold) {
            if (this.addStartTypingSuggestion({ request, records })) {
                suggestions.push(this.buildStartTypingSuggestion());
            }
        } else {
            records = await lock(this.search(request));
            ({ records, hasMore } = splitOverflow(
                records ?? [],
                this.props.searchLimit,
            ));
            if (records?.length) {
                for (const record of records) {
                    suggestions.push(this.buildRecordSuggestion(request, record));
                }
            } else if (this.addNoRecordsSuggestion()) {
                suggestions.push(this.buildNoRecordsSuggestion());
            } else if (this.addStartTypingSuggestion({ request, records })) {
                suggestions.push(this.buildStartTypingSuggestion());
            }
        }

        for (const action of this.actionSuggestions) {
            const enabled = action.enabled ?? (() => true);
            if (enabled({ request, records, hasMore })) {
                suggestions.push(action.build(request));
            }
        }

        return suggestions;
    }

    /** @returns {Array<{ enabled?: Function, build: Function }>} */
    get actionSuggestions() {
        return [
            {
                enabled: this.addCreateSuggestion.bind(this),
                build: this.buildCreateSuggestion.bind(this),
            },
            {
                enabled: this.addCreateEditSuggestion.bind(this),
                build: this.buildCreateEditSuggestion.bind(this),
            },
            {
                enabled: this.addSearchMoreSuggestion.bind(this),
                build: this.buildSearchMoreSuggestion.bind(this),
            },
        ];
    }

    /**
     * @param {{ request: string }} params
     * @returns {boolean}
     */
    addCreateSuggestion({ request }) {
        return !!this.props.quickCreate && request.length > 0;
    }

    /**
     * @param {{ records: Array|null, request: string }} params
     * @returns {boolean}
     */
    addCreateEditSuggestion({ records, request }) {
        return Boolean(
            (this.activeActions.createEdit ?? this.activeActions.create) &&
            (request.length || records?.length === 0),
        );
    }

    /**
     * @returns {boolean}
     */
    addNoRecordsSuggestion() {
        return !this.activeActions.createEdit && !this.props.quickCreate;
    }

    /**
     * @param {{ request: string, hasMore: boolean }} params
     * @returns {boolean}
     */
    addSearchMoreSuggestion({ request, hasMore }) {
        return request.length < this.props.searchThreshold || !!hasMore;
    }

    /**
     * @param {{ request: string, records: Array|null }} params
     * @returns {boolean}
     */
    addStartTypingSuggestion({ request, records }) {
        return records !== null
            ? !request.length && !this.activeActions.createEdit
            : !this.props.value;
    }

    /**
     * @param {string} request
     * @returns {Object}
     */
    buildCreateSuggestion(request) {
        return {
            cssClass: "o_m2o_dropdown_option o_m2o_dropdown_option_create",
            data: { slotName: "createItem" },
            label: _t('Create "%s"', request),
            onSelect: async () => {
                try {
                    await this.props.quickCreate(request);
                    this.invalidateEmptySearch();
                } catch (e) {
                    await this.onQuickCreateError(e, request);
                }
            },
        };
    }

    /**
     * @param {string} request
     * @returns {Object}
     */
    buildCreateEditSuggestion(request) {
        return {
            cssClass: "o_m2o_dropdown_option o_m2o_dropdown_option_create_edit",
            data: { slotName: "createEditItem" },
            label: request.length ? _t("Create and edit...") : _t("Create..."),
            onSelect: () => this.slowCreate(request),
        };
    }

    /** @returns {Object} */
    buildNoRecordsSuggestion() {
        return {
            cssClass: "o_m2o_no_result",
            data: { slotName: "noRecordsItem" },
            label: _t("No records"),
        };
    }

    /**
     * @param {string} request
     * @param {Object} record
     * @returns {Object}
     */
    buildRecordSuggestion(request, record) {
        const label = record.__formatted_display_name || record.display_name;
        return {
            data: { record, slotName: "autoCompleteItem" },
            label: label
                ? highlightText(request, odoomark(label), "text-primary fw-bold")
                : _t("Unnamed"),
            onSelect: () => this.update([record]),
        };
    }

    /**
     * @param {string} request
     * @returns {Object}
     */
    buildSearchMoreSuggestion(request) {
        return {
            cssClass: "o_m2o_dropdown_option o_m2o_dropdown_option_search_more",
            data: { slotName: "searchMoreItem" },
            label: this.searchMoreButtonLabel,
            onSelect: this.onSearchMore.bind(this, request),
        };
    }

    /** @returns {Object} */
    buildStartTypingSuggestion() {
        return {
            cssClass: "o_m2o_start_typing",
            data: { slotName: "startTypingItem" },
            label:
                this.props.searchThreshold > 1
                    ? _t("Start typing %s characters", this.props.searchThreshold)
                    : _t("Start typing..."),
        };
    }

    /** @returns {string} */
    get searchMoreButtonLabel() {
        return this.props.searchMoreLabel ?? searchMoreLabel();
    }

    async onBarcodeSearch() {
        const autoCompleteInput = /** @type {HTMLInputElement | null} */ (
            this.autoCompleteContainer.el?.querySelector("input")
        );
        if (!autoCompleteInput) {
            return;
        }
        return this.onSearchMore(autoCompleteInput.value);
    }

    /** @param {string} request */
    async onSearchMore(request) {
        const { getDomain, context, fieldString } = this.props;

        const domain = getDomain();
        let dynamicFilters = [];
        if (request.length) {
            const records = await this.nameSearch({
                name: request,
                limit: this.props.searchMoreLimit,
                domain,
                context,
                specification: {},
            });

            dynamicFilters = [
                quickSearchFilter(
                    request,
                    records.map((record) => record.id),
                ),
            ];
        }

        this.selectCreate({
            domain,
            context,
            filters: dynamicFilters,
            title: searchMoreTitle(fieldString),
        });
    }

    /** @param {{ inputValue: string }} params */
    onChange({ inputValue }) {
        if (!inputValue.length) {
            this.update(false);
        }
    }
}

/**
 * @param {Object} params
 * @param {string} params.resModel
 * @param {Function} params.onRecordSaved
 * @param {Function} params.onRecordDiscarded
 * @param {string} params.fieldString
 * @param {Object} params.activeActions
 * @param {boolean} params.isToMany
 * @param {Function} [params.onClose]
 * @param {import("@odoo/owl").ComponentConstructor | null} [params.component]
 * @param {string} [params.size]
 * @returns {Function}
 */
export function useOpenMany2XRecord({
    resModel,
    onRecordSaved,
    onRecordDiscarded,
    fieldString,
    activeActions,
    isToMany,
    onClose = (isNew) => {},
    component = null,
    size = "lg",
}) {
    component ??= getFormViewDialog();
    const addDialog = useOwnedDialogs();
    const orm = useService("orm");

    return async function openDialog(
        { resId = false, forceModel = null, title, context, nextRecordsContext },
        immediate = false,
    ) {
        const model = forceModel || resModel;
        let viewId;
        if (resId !== false) {
            viewId = await orm.call(model, "get_formview_id", [[resId]], {
                context,
            });
        }

        /** @type {(value?: any) => void} */
        let resolve = () => {};
        if (!title) {
            title = resId ? _t("Open: %s", fieldString) : _t("Create %s", fieldString);
        }

        const { create: canCreate, write: canWrite } = activeActions;
        const readonly = !(resId ? canWrite : canCreate);

        addDialog(
            component,
            {
                preventCreate: !canCreate,
                preventEdit: !canWrite,
                title,
                context,
                nextRecordsContext,
                readonly,
                resId,
                resModel: model,
                viewId,
                onRecordSaved,
                onRecordDiscarded,
                isToMany,
                size,
            },
            {
                onClose: () => {
                    resolve();
                    const isNew = !resId;
                    onClose(isNew);
                },
            },
        );

        if (!immediate) {
            return /** @type {any} */ (
                new Promise((_resolve) => {
                    resolve = _resolve;
                })
            );
        }
    };
}
