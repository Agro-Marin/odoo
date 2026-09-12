// @ts-check
/** @odoo-module native */
import { DISCUSS_SIDEBAR_COMPACT_LS } from "@mail/core/public_web/discuss_app_model";
import { Component, onMounted, useSubEnv } from "@odoo/owl";
import { ResizablePanel } from "@web/components/resizable_panel";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { ActionList } from "../common/action_list.js";
import { DiscussSearch } from "./discuss_search.js";

const log = makeLogger("mail.discuss.sidebar");

export const discussSidebarItemsRegistry = registry.category(
    "mail.discuss_sidebar_items",
);

/**
 * @typedef {Object} Props
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class DiscussSidebar extends Component {
    static template = "mail.DiscussSidebar";
    static props = {};
    static components = { ActionList, DiscussSearch, ResizablePanel };

    setup() {
        super.setup();
        this.store = useService("mail.store");
        this.ui = useService("ui");
        useSubEnv({ inDiscussSidebar: true });
        onMounted(() => {
            this.mounted = true;
        });
    }

    get discussSidebarItems() {
        return discussSidebarItemsRegistry.getAll();
    }

    /** @param {number} width */
    onResize(width) {
        if (!this.mounted) {
            return;
        }
        log.logic("onResize", () => ({ width, compact: width <= 100 }));
        if (width <= 100) {
            browser.localStorage.setItem(DISCUSS_SIDEBAR_COMPACT_LS, String(true));
        } else {
            browser.localStorage.removeItem(DISCUSS_SIDEBAR_COMPACT_LS);
        }
        this.store.discuss._recomputeIsSidebarCompact++;
    }
}
