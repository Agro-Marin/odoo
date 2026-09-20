/** @odoo-module native */
import { Component, onWillStart, useEffect, useState } from "@odoo/owl";
import { router } from "@web/core/browser/router";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { standardActionServiceProps } from "@web/webclient/actions";

import { HierarchyNavbar } from "./hierarchy_navbar.js";

const log = makeLogger("website.backend.view_hierarchy");

export class ViewHierarchy extends Component {
    static components = { Layout, HierarchyNavbar };
    static template = "website.view_hierarchy";
    static props = { ...standardActionServiceProps };
    setup() {
        useLifecycleLog(log);
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({ showInactive: false, searchedView: {}, viewTree: {} });
        this.websites = useState({
            names: new Set(["All Websites"]),
            selected: "All Websites",
        });
        this.viewId = this.props.action.context.active_id || router.current.active_id;
        this.hideGenericViewByWebsite = {};

        onWillStart(async () => {
            const endHierarchy = log.perf("get_view_hierarchy", () => ({
                viewId: this.viewId,
            }));
            ({ sibling_views: this.siblingViews, hierarchy: this.state.viewTree } =
                await this.orm.call(
                    "ir.ui.view",
                    "get_view_hierarchy",
                    [this.viewId],
                    {},
                ));
            endHierarchy();

            this.setupWebsiteNames();
            this.setupHideGenericViewByWebsite();
            this.linkViewsToParent();
            log.pipeline("hierarchy prepared", () => ({
                viewId: this.viewId,
                siblings: this.siblingViews?.length,
            }));
        });

        useEffect(
            (searchFoundElem) => {
                if (searchFoundElem) {
                    searchFoundElem.scrollIntoView({
                        behavior: "smooth",
                        block: "center",
                    });
                }
            },
            () => [document.querySelector(".o_search_found")],
        );
    }

    /**
     * @param {String} websiteName
     */
    selectWebsite(websiteName) {
        log.logic("selectWebsite", () => ({ websiteName }));
        this.websites.selected = websiteName;
    }

    /**
     * @param {Boolean} checked
     */
    toggleInactive(checked) {
        log.logic("toggleInactive", () => ({ checked }));
        this.state.showInactive = checked;
    }

    /**
     * @param {String} keyword
     * @returns {Array}
     */
    getSearchResults(keyword) {
        const exactMatches = [];
        const matches = [];
        const lowercaseKeyword = keyword.toLowerCase();
        this.viewTraversal(
            this.state.viewTree,
            (currentView) => {
                if (
                    this.isViewDisplayed(currentView) &&
                    (currentView.name.toLowerCase() === lowercaseKeyword ||
                        currentView.key.toLowerCase() === lowercaseKeyword ||
                        currentView.id === parseInt(lowercaseKeyword))
                ) {
                    exactMatches.push(currentView);
                } else if (
                    this.isViewDisplayed(currentView) &&
                    (currentView.name.toLowerCase().includes(lowercaseKeyword) ||
                        currentView.key.toLowerCase().includes(lowercaseKeyword))
                ) {
                    matches.push(currentView);
                }
            },
            (currentView) => this.isViewDisplayed(currentView),
        );
        return exactMatches.concat(matches);
    }

    /**
     * @param {String} keyword
     * @param {Boolean} forward
     */
    searchView(keyword, forward = true) {
        const matches = this.getSearchResults(keyword);
        let index = 0;
        if (this.state.searchedView.keyword === keyword) {
            index = matches.findIndex((view) => this.state.searchedView.id === view.id);
            index = forward ? index + 1 : index - 1;
            index = index - matches.length * Math.floor(index / matches.length);
        }

        const view = matches[index];
        log.logic("searchView", () => ({
            keyword,
            forward,
            matches: matches.length,
            index,
            found: !!view,
        }));
        if (view) {
            this.state.searchedView = {
                id: view.id,
                keyword: keyword,
                total: matches.length,
                index,
            };
        }
    }

    /**
     * @param {Object} currentView
     * @param {Function} fn
     * @param {Function} continueRec
     */
    viewTraversal(currentView, fn, continueRec = (view) => true) {
        fn(currentView);
        if (continueRec(currentView)) {
            currentView.inherit_children.forEach((childView) => {
                this.viewTraversal(childView, fn, continueRec);
            });
        }
    }

    setupWebsiteNames() {
        this.viewTraversal(this.state.viewTree, (currentView) => {
            if (currentView.website_name) {
                this.websites.names.add(currentView.website_name);
            }
        });
    }

    setupHideGenericViewByWebsite() {
        this.viewTraversal(this.state.viewTree, (currentView) => {
            if (currentView.website_name) {
                if (!this.hideGenericViewByWebsite[currentView.website_name]) {
                    this.hideGenericViewByWebsite[currentView.website_name] = {};
                }
                this.hideGenericViewByWebsite[currentView.website_name][
                    currentView.name
                ] = true;
            }
        });
    }

    linkViewsToParent() {
        this.viewTraversal(this.state.viewTree, (currentView) => {
            currentView.inherit_children.forEach(
                (child) => (child.parent = currentView),
            );
        });
    }

    /**
     * @param {Object} view
     */
    onCollapseClick(view) {
        view.collapsed = !view.collapsed;
        if (view.collapsed) {
            this.viewTraversal(view, (child) => {
                child.collapsed = view.collapsed;
            });
        }
    }

    /**
     * @param {Object} view
     * @param {Boolean} isCollapsedDisplayed
     */
    isViewDisplayed(view, isCollapsedDisplayed = false) {
        let isCollapsed = view.parent ? view.parent.collapsed : false;
        if (isCollapsedDisplayed) {
            isCollapsed = false;
        }
        const isActive = this.state.showInactive || view.active;
        const isWebsiteDisplayed =
            this.websites.selected === "All Websites" ||
            view.website_name === this.websites.selected ||
            (!view.website_name &&
                !this.hideGenericViewByWebsite[this.websites.selected][view.name]);
        return !isCollapsed && isActive && isWebsiteDisplayed;
    }

    /**
     * @param {Object} view
     */
    hasChildToUnfold(view) {
        return view.inherit_children.some((child) => this.isViewDisplayed(child, true));
    }

    /**
     * @param {Number} viewId
     */
    onShowDiffClick(viewId) {
        log.lifecycle("open reset view arch wizard", () => ({ viewId }));
        this.action.doAction("base.reset_view_arch_wizard_action", {
            additionalContext: {
                active_model: "ir.ui.view",
                active_ids: [viewId],
            },
        });
    }

    /**
     * @param {Number} viewId
     */
    openFormView(viewId) {
        log.lifecycle("open view form", () => ({ viewId }));
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "ir.ui.view",
            res_id: viewId,
            views: [[false, "form"]],
        });
    }

    /**
     * @param {Number} viewId
     */
    onShowHierarchy(viewId) {
        log.lifecycle("open view hierarchy", () => ({ viewId }));
        this.action.doAction({
            type: "ir.actions.client",
            tag: "website_view_hierarchy",
            name: "View Hierarchy",
            context: {
                active_id: viewId,
            },
        });
    }
}

registry.category("actions").add("website_view_hierarchy", ViewHierarchy);
