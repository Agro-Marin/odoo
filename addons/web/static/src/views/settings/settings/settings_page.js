// @ts-check
/** @odoo-module native */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { ActionSwiper } from "@web/components/action_swiper/action_swiper";
import { browser } from "@web/core/browser/browser";
import { Deferred } from "@web/core/utils/concurrency";
export class SettingsPage extends Component {
    static template = "web.SettingsPage";
    static components = { ActionSwiper };
    static props = {
        modules: Array,
        anchors: Array,
        initialTab: { type: String, optional: 1 },
        slots: Object,
    };
    /** @type {import("@odoo/owl").Ref} */
    settingsRef;
    /** @type {import("@odoo/owl").Ref} */
    settingsTabRef;
    /** @type {{ selectedTab: string; search: any }} */
    state;
    /** @type {import("@web/core/utils/concurrency").Deferred | undefined} */
    tabChangeProm;

    setup() {
        this.state = useState({
            selectedTab: "",
            search: this.env.searchState,
        });

        if (this.props.modules.length) {
            let selectedTab = this.props.initialTab || this.props.modules[0].key;

            if (browser.location.hash) {
                const hash = browser.location.hash.slice(1);
                if (
                    this.props.modules
                        .map((/** @type {any} */ m) => m.key)
                        .includes(hash)
                ) {
                    selectedTab = hash;
                } else {
                    const anchor = this.props.anchors.find(
                        (/** @type {any} */ a) => a.settingId === hash,
                    );
                    if (anchor) {
                        selectedTab = anchor.app;
                    }
                }
            }

            this.state.selectedTab = selectedTab;
        }

        this.settingsRef = useRef("settings");
        this.settingsTabRef = useRef("settings_tab");
        this.scrollMap = Object.create(null);
        useEffect(
            (settingsEl, currentTab) => {
                if (!settingsEl) {
                    return;
                }

                const { scrollTop } = this.scrollMap[currentTab] || { scrollTop: 0 };
                settingsEl.scrollTop = scrollTop;
                this.tabChangeProm?.resolve();
            },
            () => [this.settingsRef.el, this.state.selectedTab],
        );
    }

    getCurrentIndex() {
        return this.props.modules.findIndex(
            (/** @type {any} */ object) => object.key === this.state.selectedTab,
        );
    }

    hasRightSwipe() {
        return (
            this.env.isSmall &&
            !this.state.search.value.length &&
            this.getCurrentIndex() !== 0
        );
    }
    hasLeftSwipe() {
        return (
            this.env.isSmall &&
            !this.state.search.value.length &&
            this.getCurrentIndex() !== this.props.modules.length - 1
        );
    }
    async onRightSwipe() {
        this.tabChangeProm = new Deferred();
        this.state.selectedTab = this.props.modules[this.getCurrentIndex() - 1].key;
        await this.tabChangeProm;
        this.scrollToSelectedTab();
    }
    async onLeftSwipe() {
        this.tabChangeProm = new Deferred();
        this.state.selectedTab = this.props.modules[this.getCurrentIndex() + 1].key;
        await this.tabChangeProm;
        this.scrollToSelectedTab();
    }

    scrollToSelectedTab() {
        const key = this.state.selectedTab;
        this.settingsTabRef.el?.querySelector(`[data-key='${key}']`)?.scrollIntoView({
            behavior: "smooth",
            inline: "center",
            block: "nearest",
        });
    }

    /** @param {string} key */
    onSettingTabClick(key) {
        if (this.settingsRef.el) {
            const { scrollTop } = this.settingsRef.el;
            this.scrollMap[this.state.selectedTab] = { scrollTop };
        }
        this.state.selectedTab = key;
        this.env.searchState.value = "";
    }
}
