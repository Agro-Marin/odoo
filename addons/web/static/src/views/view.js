// @ts-check
/** @odoo-module native */

/** @module @web/views/view */

import {
    Component,
    markRaw,
    onWillStart,
    onWillUpdateProps,
    reactive,
    toRaw,
    useSubEnv,
} from "@odoo/owl";
import { useDebugCategory } from "@web/core/debug/debug_context";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { deepCopy } from "@web/core/utils/collections/objects";
import { KeepLast } from "@web/core/utils/concurrency";
import { parseXML } from "@web/core/utils/dom/xml";
import { nbsp } from "@web/core/utils/format/strings";
import { useService } from "@web/core/utils/hooks";
import { extractLayoutComponents } from "@web/search/layout";
import { WithSearch } from "@web/search/with_search/with_search";
import { session } from "@web/session";
import { useActionLinks } from "@web/views/view_hook";

import { computeViewClassName } from "./view_utils.js";

/**
 * @typedef Config
 * @property {number | false} actionId
 * @property {string | false} actionType
 * @property {() => []} breadcrumbs
 * @property {() => string} getDisplayName
 * @property {(name: string) => any} setDisplayName
 * @property {() => Record<string, any>} [getPagerProps]
 * @property {Record<string, any>[]} [viewSwitcherEntry]
 * @property {typeof Component} [Banner]
 * @typedef {import("@web/core/context").Context} Context
 * @typedef {import("@web/env").OdooEnv} OdooEnv
 * @typedef {import("@web/core/utils/order_by").OrderTerm} OrderTerm
 * @typedef ViewProps
 * @property {string} resModel
 * @property {ViewType} type
 * @property {string} [arch]
 * @property {Record<string, any>} [fields]
 * @property {Record<string, any>} [relatedModels]
 * @property {number|false} [viewId]
 * @property {[number|false, string][]} [views]
 * @property {Record<string, any>} [actionMenus]
 * @property {boolean} [loadActionMenus=false]
 * @property {string} [searchViewArch]
 * @property {Record<string, any>} [searchViewFields]
 * @property {number|false} [searchViewId]
 * @property {Record<string, any>[]} [irFilters]
 * @property {boolean} [loadIrFilters=false]
 * @property {Record<string, any>} [comparison]
 * @property {Context} [context={}]
 * @property {any} [domain]
 * @property {string[]} [groupBy]
 * @property {OrderTerm[]} [orderBy]
 * @property {boolean} [useSampleModel]
 * @property {string|false} [noContentHelp]
 * @property {string} [className]
 * @property {string} [jsClass]
 * @property {boolean} [noBreadcrumbs]
 * @property {Record<string, any>} [display={}]
 * @property {boolean} [activateFavorite]
 * @property {Record<string, any>[]} [dynamicFilters]
 * @property {boolean} [hideCustomGroupBy]
 * @property {string[]} [searchMenuTypes]
 * @property {Record<string, any>} [globalState]
 * @typedef {"activity"
 *  | "calendar"
 *  | "cohort"
 *  | "form"
 *  | "gantt"
 *  | "graph"
 *  | "grid"
 *  | "hierarchy"
 *  | "kanban"
 *  | "list"
 *  | "map"
 *  | "pivot"
 *  | "search"
 * } ViewType
 */

const viewRegistry = registry.category("views");

viewRegistry.addValidation({
    type: { validate: (t) => t in session.view_info },
    Controller: { validate: (c) => c.prototype instanceof Component },
    "*": true,
});

export function getDefaultConfig() {
    const breadcrumbReactive = reactive([{ name: undefined }]);
    const config = {
        actionId: false,
        actionType: false,
        cache: true,
        actionXmlId: false,
        embeddedActions: [],
        currentEmbeddedActionId: false,
        parentActionId: false,
        breadcrumbs: breadcrumbReactive,
        disableSearchBarAutofocus: false,
        getDisplayName: () => breadcrumbReactive[0].name,
        historyBack: () => {},
        pagerProps: {},
        setDisplayName: (newDisplayName) => {
            breadcrumbReactive[0].name = newDisplayName;
        },
        viewSwitcherEntries: [],
        views: [],
    };
    return config;
}

export class ViewNotFoundError extends Error {}

const CALLBACK_RECORDER_NAMES = [
    "__beforeLeave__",
    "__getGlobalState__",
    "__getLocalState__",
    "__getContext__",
    "__getOrderBy__",
];

/**
 * Declared types for every prop `View` is known to receive, as an OWL schema.
 *
 * `View` cannot use a closed schema: `loadView` deliberately forwards every prop
 * it does not consume itself to the controller (the `STANDARD_PROPS` filter
 * below), so third-party callers legitimately pass keys this module has never
 * heard of. `"*": true` keeps that door open while the declared keys above it
 * are still checked -- OWL's `validateSchema` honours both in the same schema.
 *
 * Validation runs in dev mode only, so this buys nothing at runtime in
 * production. What it buys is that `web`'s two widest extension seams stop
 * accepting a misspelled or wrongly-typed prop in silence during development and
 * in every Hoot suite.
 *
 * Contains a superset of `STANDARD_PROPS`: `comparison` and `noBreadcrumbs` are
 * documented `ViewProps` that are deliberately *not* in that list, because they
 * are meant to reach the controller. Declaring a type for them here does not
 * change where they go -- forwarding is decided by `STANDARD_PROPS` alone, which
 * is left exactly as it was. `view_props.test.js` pins that every
 * `STANDARD_PROPS` entry carries a declared type, so the two cannot drift apart
 * silently the way two hand-maintained lists otherwise do.
 */
export const viewProps = {
    // Declared `optional` although both are in fact mandatory: `setup()` already
    // rejects a missing `resModel` / `type` with a message naming the key, which
    // is more use than OWL's generic "'type' is missing". Marking them required
    // here would make the schema throw first and swallow that. Present values
    // are still type-checked.
    resModel: { type: String, optional: true },
    type: { type: String, optional: true },
    jsClass: { type: String, optional: true },

    arch: { type: String, optional: true },
    fields: { type: Object, optional: true },
    relatedModels: { type: Object, optional: true },
    viewId: { type: [Number, Boolean], optional: true },
    views: { type: Array, optional: true },
    actionMenus: { type: Object, optional: true },
    loadActionMenus: { type: Boolean, optional: true },

    searchViewArch: { type: String, optional: true },
    searchViewFields: { type: Object, optional: true },
    searchViewId: { type: [Number, Boolean], optional: true },
    irFilters: { type: Array, optional: true },
    loadIrFilters: { type: Boolean, optional: true },

    context: { type: Object, optional: true },
    domain: { type: Array, optional: true },
    groupBy: { type: Array, element: String, optional: true },
    orderBy: { type: Array, optional: true },
    comparison: { type: Object, optional: true },

    useSampleModel: { type: Boolean, optional: true },
    // `false`, not just a string: this is `action.help` forwarded verbatim by
    // `action_info_builders` (`viewProps.noContentHelp = action.help`), and an
    // `ir.actions.act_window` with an empty Html `help` serialises it as
    // `false`. That value is load-bearing rather than incidental --
    // `PivotController.displayNoContent` branches on
    // `noContentHelp === false` -- so declaring it `String` rejected an action
    // the webclient opens routinely, and did so only in dev mode, which is
    // where the tours run.
    noContentHelp: { type: [String, Boolean], optional: true },
    className: { type: String, optional: true },
    noBreadcrumbs: { type: Boolean, optional: true },

    display: { type: Object, optional: true },
    globalState: { type: Object, optional: true },

    activateFavorite: { type: Boolean, optional: true },
    dynamicFilters: { type: Array, optional: true },
    hideCustomGroupBy: { type: Boolean, optional: true },
    searchMenuTypes: { type: Array, element: String, optional: true },

    __beforeLeave__: { type: Object, optional: true },
    __getGlobalState__: { type: Object, optional: true },
    __getLocalState__: { type: Object, optional: true },
    __getContext__: { type: Object, optional: true },
    __getOrderBy__: { type: Object, optional: true },

    searchPanel: { type: Object, optional: true },
    searchModel: { type: Object, optional: true },

    "*": true,
};

export const STANDARD_PROPS = [
    "resModel",
    "type",
    "jsClass",

    "arch",
    "fields",
    "relatedModels",
    "viewId",
    "views",
    "actionMenus",
    "loadActionMenus",

    "searchViewArch",
    "searchViewFields",
    "searchViewId",
    "irFilters",
    "loadIrFilters",

    "context",
    "domain",
    "groupBy",
    "orderBy",

    "useSampleModel",
    "noContentHelp",
    "className",

    "display",
    "globalState",

    "activateFavorite",
    "dynamicFilters",
    "hideCustomGroupBy",
    "searchMenuTypes",

    ...CALLBACK_RECORDER_NAMES,

    "searchPanel",
    "searchModel",
];

const ACTIONS = [
    "create",
    "delete",
    "edit",
    "group_create",
    "group_delete",
    "group_edit",
];

/** @extends {Component<ViewProps, import("@web/env").OdooEnv>} */
export class View extends Component {
    static template = "web.View";
    static components = { WithSearch };
    static searchMenuTypes = ["filter", "groupBy", "favorite"];
    static canOrderByCount = false;

    /**
     * @type {number}
     */
    loadViewId;
    static defaultProps = {
        display: {},
        context: {},
        loadActionMenus: false,
        loadIrFilters: false,
        className: "",
    };
    static props = viewProps;

    /** @type {import("services").ServiceFactories["view"]} */
    viewService;
    /** @type {Record<string, any> | null} */
    withSearchProps;

    setup() {
        const { arch, fields, resModel, searchViewArch, searchViewFields, type } =
            this.props;
        if (!resModel) {
            throw Error(`View props should have a "resModel" key`);
        }
        if (!type) {
            throw Error(`View props should have a "type" key`);
        }
        if ((arch && !fields) || (!arch && fields)) {
            throw new Error(`"arch" and "fields" props must be given together`);
        }
        if (
            (searchViewArch && !searchViewFields) ||
            (!searchViewArch && searchViewFields)
        ) {
            throw new Error(
                `"searchViewArch" and "searchViewFields" props must be given together`,
            );
        }

        this.viewService = useService("view");
        this.withSearchProps = null;
        this.loadViewId = 0;

        useSubEnv({
            keepLast: new KeepLast(),
            config: {
                ...getDefaultConfig(),
                ...this.env.config,
            },
            ...Object.fromEntries(
                CALLBACK_RECORDER_NAMES.map((name) => [name, this.props[name] || null]),
            ),
        });

        this.handleActionLinks = useActionLinks({ resModel });

        onWillStart(() => this.loadView(this.props));
        onWillUpdateProps((nextProps) => this.onWillUpdateProps(nextProps));

        useDebugCategory("view", { component: this });
    }

    /**
     * @param {ViewProps} props
     */
    async loadView(props) {
        const loadId = ++this.loadViewId;
        const type = props.type;
        const config = /** @type {Record<string, any>} */ (this.env.config);

        if (!session.view_info[type]) {
            throw new Error(`Invalid view type: ${type}`);
        }

        let { viewId, searchViewId } = props;

        const views = deepCopy(props.views || config.views);
        const view = views.find((v) => v[1] === type) || [];
        if (view.length) {
            view[0] = viewId !== undefined ? viewId : view[0];
            viewId = view[0];
        } else {
            view.push(viewId || false, type);
            views.push(view);
        }

        const searchView = views.find((v) => v[1] === "search");
        if (searchView) {
            searchView[0] = searchViewId !== undefined ? searchViewId : searchView[0];
            searchViewId = searchView[0];
        } else if (searchViewId !== undefined) {
            views.push([searchViewId, "search"]);
        }

        const { resModel, loadActionMenus, loadIrFilters } = props;
        const context = /** @type {Record<string, any>} */ (props.context ?? {});
        let {
            arch,
            fields,
            relatedModels,
            searchViewArch,
            searchViewFields,
            irFilters,
            actionMenus,
        } = props;

        const hasSearchView = views.some((v) => v[1] === "search");
        const loadView = !arch || (!actionMenus && loadActionMenus);
        const loadSearchView =
            hasSearchView &&
            ((searchViewId !== undefined && !searchViewArch) ||
                (!irFilters && loadIrFilters));

        /** @type {any} */
        let viewDescription = { id: viewId, resModel, type };
        let searchViewDescription;
        if (loadView || loadSearchView) {
            const options = {
                actionId: config.actionId,
                loadActionMenus,
                loadIrFilters: loadIrFilters && hasSearchView,
            };
            if (config.currentEmbeddedActionId) {
                options.embeddedActionId = config.currentEmbeddedActionId;
                options.embeddedParentResId = context.active_id;
            }
            const result = await this.viewService.loadViews(
                { context, resModel, views },
                options,
            );
            if (loadId !== this.loadViewId) {
                return;
            }
            viewDescription = result.views[type];
            searchViewDescription = /** @type {any} */ (result.views).search;
            if (loadSearchView) {
                searchViewId = searchViewId || searchViewDescription.id;
                if (!searchViewArch) {
                    searchViewArch = searchViewDescription.arch;
                    searchViewFields = result.fields;
                }
                if (!irFilters) {
                    irFilters = searchViewDescription.irFilters;
                }
            }
            fields = fields || markRaw(result.fields);
            relatedModels = relatedModels || markRaw(result.relatedModels);
        }

        config.views = views;

        if (!arch) {
            arch = viewDescription.arch;
        }
        if (!actionMenus) {
            actionMenus = viewDescription.actionMenus;
        }

        const archXmlDoc = parseXML((arch ?? "").replaceAll("&amp;nbsp;", nbsp));
        for (const action of ACTIONS) {
            if (action in context && !context[action]) {
                archXmlDoc.setAttribute(action, "0");
            }
        }

        const jsClass = archXmlDoc.hasAttribute("js_class")
            ? /** @type {string} */ (archXmlDoc.getAttribute("js_class"))
            : props.jsClass || type;
        const descr = /** @type {any} */ (viewRegistry.get(jsClass));

        const sample = archXmlDoc.getAttribute("sample");
        const className = computeViewClassName(type, archXmlDoc, [
            "o_view_controller",
            ...(props.className || "").split(" "),
        ]);

        Object.assign(config, {
            rawArch: arch,
            viewArch: archXmlDoc,
            viewId: viewDescription.id,
            viewType: type,
            viewSubType: jsClass,
            noBreadcrumbs: props.noBreadcrumbs,
            ...extractLayoutComponents(descr),
        });
        const info = {
            actionMenus,
            mode: props.display?.mode,
            irFilters,
            searchViewArch,
            searchViewFields,
            searchViewId,
        };

        const viewProps = {
            info,
            arch: archXmlDoc,
            fields,
            relatedModels,
            resModel,
            useSampleModel: false,
            className,
        };
        if (viewDescription.custom_view_id) {
            viewProps.info.customViewId = viewDescription.custom_view_id;
        }
        if (props.globalState) {
            viewProps.globalState = props.globalState;
        }

        if ("useSampleModel" in props) {
            viewProps.useSampleModel = /** @type {boolean} */ (props.useSampleModel);
        } else if (sample) {
            viewProps.useSampleModel = evaluateBooleanExpr(sample);
        }

        for (const key of Object.keys(props)) {
            if (!STANDARD_PROPS.includes(key)) {
                viewProps[key] = props[key];
            }
        }

        const { noContentHelp } = props;
        if (noContentHelp) {
            viewProps.info.noContentHelp = noContentHelp;
        }

        const searchMenuTypes =
            props.searchMenuTypes ||
            descr.searchMenuTypes ||
            /** @type {any} */ (this.constructor).searchMenuTypes;
        const defaultGroupBy = archXmlDoc.hasAttribute("default_group_by")
            ? (archXmlDoc.getAttribute("default_group_by") ?? "").split(",")
            : null;
        viewProps.searchMenuTypes = searchMenuTypes;
        const canOrderByCount =
            descr.canOrderByCount ||
            /** @type {any} */ (this.constructor).canOrderByCount;

        const finalProps = descr.props
            ? descr.props(viewProps, descr, config)
            : viewProps;
        this.Controller = descr.Controller;
        this.componentProps = finalProps;
        /** @type {Record<string, any>} */
        this.withSearchProps = {
            ...toRaw(props),
            hideCustomGroupBy: props.hideCustomGroupBy || descr.hideCustomGroupBy,
            searchMenuTypes,
            canOrderByCount,
            SearchModel: descr.SearchModel,
        };

        if (searchViewId !== undefined) {
            this.withSearchProps.searchViewId = searchViewId;
        }
        if (searchViewArch) {
            this.withSearchProps.searchViewArch = searchViewArch;
            this.withSearchProps.searchViewFields = searchViewFields;
        }
        if (irFilters) {
            this.withSearchProps.irFilters = irFilters;
        }

        if (descr.display) {
            const viewDisplay = deepCopy(descr.display);
            const display = { ...this.withSearchProps.display };
            for (const key of Object.keys(viewDisplay)) {
                const current = display[key];
                if (current && typeof current === "object") {
                    display[key] = { ...current, ...viewDisplay[key] };
                } else if (!(key in display) || current) {
                    display[key] = viewDisplay[key];
                }
            }
            this.withSearchProps.display = display;
        }

        if (defaultGroupBy?.length) {
            this.withSearchProps.defaultGroupBy = defaultGroupBy;
        }

        for (const key of Object.keys(this.withSearchProps)) {
            if (!(key in WithSearch.props)) {
                delete this.withSearchProps[key];
            }
        }
    }

    /**
     * @param {ViewProps} nextProps
     */
    onWillUpdateProps(nextProps) {
        if (
            this.props.arch !== nextProps.arch ||
            this.props.type !== nextProps.type ||
            this.props.resModel !== nextProps.resModel
        ) {
            return this.loadView(nextProps);
        }
        const { context, domain, groupBy, orderBy } = nextProps;
        Object.assign(/** @type {Record<string, any>} */ (this.withSearchProps), {
            context,
            domain,
            groupBy,
            orderBy,
        });
    }
}
