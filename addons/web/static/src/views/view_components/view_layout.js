// @ts-check
/** @odoo-module native */

import { Component, useComponent, useRef } from "@odoo/owl";
import { useChildRef } from "@web/core/utils/hooks";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { ActionHelper } from "@web/views/action_helper";

/**
 * @typedef ViewLayoutProps
 * @property {Record<string, any>} [slots]
 * @property {string} [className]
 * @property {(ref: any) => void} [rootRef]
 * @property {string} [contentClassName]
 * @property {Record<string, any>} [display]
 * @property {Record<string, any>} [searchBarToggler]
 * @property {boolean} [searchBar]
 * @property {boolean} [showSearchBarToggler]
 * @property {boolean} [autofocusSearchBar]
 * @property {boolean} [cogMenu]
 * @property {boolean} [useSampleModel]
 * @property {boolean} [displayNoContent]
 * @property {string} [noContentHelp]
 */

/** @extends {Component<ViewLayoutProps, import("@web/env").OdooEnv>} */
export class ViewLayout extends Component {
    static template = "web.ViewLayout";
    static components = { Layout, SearchBar, CogMenu, ActionHelper };
    static props = {
        slots: { type: Object, optional: true },
        className: { type: String, optional: true },
        contentClassName: { type: String, optional: true },
        rootRef: { type: Function, optional: true },
        display: { type: Object, optional: true },
        searchBarToggler: { type: Object, optional: true },
        searchBar: { type: Boolean, optional: true },
        showSearchBarToggler: { type: Boolean, optional: true },
        autofocusSearchBar: { type: Boolean, optional: true },
        cogMenu: { type: Boolean, optional: true },
        useSampleModel: { type: Boolean, optional: true },
        displayNoContent: { type: Boolean, optional: true },
        noContentHelp: { type: String, optional: true },
    };
    static defaultProps = {
        className: "",
        display: {},
        searchBar: true,
        showSearchBarToggler: true,
        cogMenu: true,
        autofocusSearchBar: false,
        useSampleModel: false,
        displayNoContent: false,
    };

    setup() {
        const ref = useRef("root");
        this.props.rootRef?.(ref);
    }

    /**
     * @param {string} name
     * @returns {boolean}
     */
    hasSlot(name) {
        return Boolean(this.props.slots?.[name]);
    }

    /** @returns {string} */
    get layoutClassName() {
        return [
            this.props.useSampleModel ? "o_view_sample_data" : "",
            this.props.contentClassName || "",
        ]
            .filter(Boolean)
            .join(" ");
    }
}

/**
 * @param {{
 * @returns {{ searchBarToggler: any, rootRef: any, props: ViewLayoutProps }}
 */
export function useViewChassis(hooks = {}) {
    const component = /** @type {any} */ (useComponent());
    const searchBarToggler = useSearchBarToggler();
    const forwardRootRef = useChildRef();
    const rootRef = {
        get el() {
            return forwardRootRef.el;
        },
    };

    const getModel = () => (hooks.model ? hooks.model() : component.model);

    /** @returns {boolean} */
    const displayNoContent = () => {
        if (hooks.displayNoContent) {
            return hooks.displayNoContent();
        }
        const model = getModel();
        if (!model) {
            return false;
        }
        if (component.props.info?.noContentHelp === false) {
            return false;
        }
        return !model.hasData() || Boolean(model.useSampleModel);
    };

    return {
        searchBarToggler,
        rootRef,
        get props() {
            const model = getModel();
            const noContentHelp = component.props.info?.noContentHelp;
            return {
                rootRef: forwardRootRef,
                className: component.props.className,
                display: hooks.display ? hooks.display() : component.props.display,
                searchBarToggler,
                useSampleModel: Boolean(model?.useSampleModel),
                displayNoContent: displayNoContent(),
                ...(noContentHelp ? { noContentHelp } : {}),
            };
        },
    };
}
