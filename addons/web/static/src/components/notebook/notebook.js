// @ts-check
/** @odoo-module native */

/** @module @web/components/notebook/notebook */

import {
    Component,
    onWillRender,
    onWillUpdateProps,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";

/**
 * @extends Component
 */

export class Notebook extends Component {
    static template = "web.Notebook";
    static defaultProps = {
        className: "",
        orientation: "horizontal",
        onPageUpdate: () => {},
        onWillActivatePage: () => {},
    };
    static props = {
        slots: { type: Object, optional: true },
        pages: { type: Object, optional: true },
        class: { optional: true },
        className: { type: String, optional: true },
        defaultPage: { type: String, optional: true },
        orientation: { type: String, optional: true },
        icons: { type: Object, optional: true },
        onPageUpdate: { type: Function, optional: true },
        onWillActivatePage: { type: Function, optional: true },
        isFieldInvalid: { type: Function, optional: true },
    };

    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    activePane;
    /** @type {Array<[string, Object]>} */
    pages;
    /** @type {Set<string>} */
    invalidPages;
    /** @type {{ currentPage: string | null }} */
    state;
    /** @type {string[]} */
    disabledPages;

    setup() {
        /** @type {import("@odoo/owl").Ref<HTMLElement>} */
        this.activePane = useRef("activePane");
        /** @type {Array<[string, Object]>} */
        this.pages = this.computePages(this.props);
        /** @type {Set<string>} */
        this.invalidPages = new Set();
        this.state = useState({ currentPage: null });
        this.state.currentPage = this.computeActivePage(this.props.defaultPage, true);
        this.keepLastPageTransition = new KeepLast({ rejectSuperseded: true });
        useEffect(
            () => {
                this.props.onPageUpdate(this.state.currentPage);
            },
            () => [this.state.currentPage],
        );
        useEffect(
            (pane) => {
                pane?.classList.add("show");
            },
            () => [this.activePane.el],
        );
        onWillRender(() => {
            this.computeInvalidPages();
        });
        onWillUpdateProps((nextProps) => {
            const activateDefault =
                this.props.defaultPage !== nextProps.defaultPage ||
                !this.defaultVisible;
            this.pages = this.computePages(nextProps);
            this.state.currentPage = this.computeActivePage(
                nextProps.defaultPage,
                activateDefault,
            );
        });
    }

    /** @returns {Array<[string, Object]>} */
    get navItems() {
        return this.pages.filter((e) => e[1].isVisible);
    }

    /** @returns {Object | undefined} */
    get page() {
        const entry = this.pages.find((e) => e[0] === this.state.currentPage);
        if (!entry) {
            return undefined;
        }
        const page = entry[1];
        return page.Component ? page : undefined;
    }

    /**
     * @param {string} pageIndex
     */
    async activatePage(pageIndex) {
        const exists = this.pages.some(([id]) => id === pageIndex);
        if (
            !exists ||
            this.disabledPages.includes(pageIndex) ||
            this.state.currentPage === pageIndex
        ) {
            return;
        }
        const prom = (async () => this.props.onWillActivatePage(pageIndex))();
        let canProceed;
        try {
            canProceed = await /** @type {KeepLast} */ (
                this.keepLastPageTransition
            ).add(prom);
        } catch (error) {
            if (error instanceof SupersededError) {
                return;
            }
            throw error;
        }
        if (canProceed !== false) {
            this.state.currentPage = pageIndex;
        }
    }

    /**
     * @param {Object} props
     * @returns {Array<[string, Object]>}
     */
    computePages(props) {
        this.disabledPages = [];
        if (!props.slots && !props.pages) {
            return [];
        }
        /** @type {[string, any][]} */
        const pages = [];
        /** @type {[string, any][]} */
        const pagesWithIndex = [];
        const entries = [
            ...Object.entries(props.slots || {}),
            ...(props.pages || []).map(
                /** @returns {[string, any]} */
                (page, i) => [String(i), { ...page, isVisible: true }],
            ),
        ];
        for (const [k, v] of entries) {
            const id = v.id || k;
            if (v.index !== undefined) {
                pagesWithIndex.push([id, v]);
            } else {
                pages.push([id, v]);
            }
            if (v.isDisabled) {
                this.disabledPages.push(id);
            }
        }
        pagesWithIndex.sort((a, b) => a[1].index - b[1].index);
        for (const page of pagesWithIndex) {
            pages.splice(page[1].index, 0, page);
        }
        return pages;
    }

    /**
     * @param {string | undefined} defaultPage
     * @param {boolean} activateDefault
     * @returns {string | null}
     */
    computeActivePage(defaultPage, activateDefault) {
        if (!this.pages.length) {
            return null;
        }
        const pages = this.pages.filter((e) => e[1].isVisible).map((e) => e[0]);

        if (defaultPage) {
            if (!pages.includes(defaultPage)) {
                this.defaultVisible = false;
            } else {
                this.defaultVisible = true;
                if (activateDefault) {
                    return defaultPage;
                }
            }
        }
        const current = this.state.currentPage;
        if (!current || (current && !pages.includes(current))) {
            return pages[0];
        }

        return current;
    }

    computeInvalidPages() {
        const isFieldInvalid = this.props.isFieldInvalid;
        if (!isFieldInvalid) {
            if (this.invalidPages.size) {
                this.invalidPages = new Set();
            }
            return;
        }
        const invalidPages = new Set();
        for (const [id, page] of this.navItems) {
            if (page.fieldNames?.some((fieldName) => isFieldInvalid(fieldName))) {
                invalidPages.add(id);
            }
        }
        this.invalidPages = invalidPages;
    }
}
