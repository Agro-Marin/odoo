// @ts-check
/** @odoo-module native */

import { Component, useComponent } from "@odoo/owl";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { ActionHelper } from "@web/views/action_helper";

/**
 * The control-panel chassis every multi-record view needs, as one component.
 *
 * It exists because the chassis lives in a *template* -- `Layout` plus five
 * named slots, a sample-data class, a root ref and a no-content branch -- and
 * inheritance cannot share a template. `MultiRecordController` and
 * `ReportController` were written to absorb this and could not: taking the base
 * class saved a view none of the XML, so every view type rewrote the XML, and
 * each rewrite dropped something different (a mobile search-bar toggler here, a
 * no-content helper there).
 *
 * Everything is optional and defaults to on, so *omitting* a capability is no
 * longer how a view loses it -- opting out is `searchBar="false"`, which is
 * greppable and reviewable.
 *
 * @typedef ViewLayoutProps
 * @property {Record<string, any>} [slots]
 * @property {string} [className] on the view root
 * @property {string} [contentClassName] on `Layout`'s content, beside the sample-data class
 * @property {Record<string, any>} [display]
 * @property {Record<string, any>} [searchBarToggler] from {@link useViewChassis}
 * @property {boolean} [searchBar]
 * @property {boolean} [autofocusSearchBar]
 * @property {boolean} [cogMenu]
 * @property {boolean} [useSampleModel] applies `o_view_sample_data`
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
        display: { type: Object, optional: true },
        searchBarToggler: { type: Object, optional: true },
        searchBar: { type: Boolean, optional: true },
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
        cogMenu: true,
        autofocusSearchBar: false,
        useSampleModel: false,
        displayNoContent: false,
    };

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
 * The controller half of {@link ViewLayout}: builds the props it consumes, so
 * the two cannot drift.
 *
 * `<ViewLayout t-props="chassis.props"/>`, with individual attributes after the
 * `t-props` for anything a view overrides.
 *
 * @param {{
 * model?: () => any,
 * displayNoContent?: () => boolean,
 * display?: () => Record<string, any>,
 * }} [hooks]
 * @returns {{ searchBarToggler: any, props: ViewLayoutProps }}
 */
export function useViewChassis(hooks = {}) {
    const component = /** @type {any} */ (useComponent());
    const searchBarToggler = useSearchBarToggler();

    const getModel = () => (hooks.model ? hooks.model() : component.model);

    /**
     * A view with no `noContentHelp` still shows `ActionHelper`'s default text,
     * which is why this does not test the help itself: an empty view saying
     * nothing at all is the defect, not a missing string.
     *
     * @returns {boolean}
     */
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
        get props() {
            const model = getModel();
            const noContentHelp = component.props.info?.noContentHelp;
            return {
                className: component.props.className,
                display: hooks.display ? hooks.display() : component.props.display,
                searchBarToggler,
                useSampleModel: Boolean(model?.useSampleModel),
                displayNoContent: displayNoContent(),
                // Truthiness, not `typeof`: `noContentHelp` is `false` when the
                // action suppresses the helper, and a `markup()` object -- which
                // is an object, not a primitive -- when it carries one.
                ...(noContentHelp ? { noContentHelp } : {}),
            };
        },
    };
}
