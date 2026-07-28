// @ts-check
/** @odoo-module native */

/** @module @web/components/notebook/notebook - Tabbed notebook component that renders one page at a time with tab navigation */

import {
    Component,
    onWillRender,
    onWillUpdateProps,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { KeepLast } from "@web/core/utils/concurrency";

/**
 * A notebook component that will render only the current page and allow
 * switching between its pages.
 *
 * You can also set pages using a template component. Use an array with
 * the `pages` props to do such rendering.
 *
 * Pages can also specify their index in the notebook.
 *
 *      e.g.:
 *          PageTemplate.template = xml`
                    <h1 t-esc="props.heading" />
                    <p t-esc="props.text" />`;

 *      `pages` could be:
 *      [
 *          {
 *              Component: PageTemplate,
 *              id: 'unique_id' // optional: can be given as defaultPage props to the notebook
 *              index: 1 // optional: page position in the notebook
 *              name: 'some_name' // optional
 *              title: "Some Title 1", // title displayed on the tab pane
 *              props: {
 *                  heading: "Page 1",
 *                  text: "Text Content 1",
 *              },
 *          },
 *          {
 *              Component: PageTemplate,
 *              title: "Some Title 2",
 *              props: {
 *                  heading: "Page 2",
 *                  text: "Text Content 2",
 *              },
 *          },
 *      ]
 *
 * <Notebook pages="pages">
 *    <t t-set-slot="Page Name 1" title="Some Title" isVisible="bool">
 *      <div>Page Content 1</div>
 *    </t>
 *    <t t-set-slot="Page Name 2" title="Some Title" isVisible="bool">
 *      <div>Page Content 2</div>
 *    </t>
 * </Notebook>
 *
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
        /** @type {Set<string>} page IDs with invalid fields */
        this.invalidPages = new Set();
        this.state = useState({ currentPage: null });
        this.state.currentPage = this.computeActivePage(this.props.defaultPage, true);
        this.keepLastPageTransition = new KeepLast();
        useEffect(
            () => {
                this.props.onPageUpdate(this.state.currentPage);
            },
            () => [this.state.currentPage],
        );
        // The pane is keyed on the active page, so a real page switch mounts a
        // fresh (opacity-0) element that this fades in. Keying `show` to the
        // element rather than to `currentPage` is what makes an A -> B -> A
        // sequence safe: both writes land before OWL patches, so the pane is
        // reused and stays visible instead of being left permanently faded out.
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

    /** @returns {Array<[string, Object]>} visible page entries for tab navigation */
    get navItems() {
        return this.pages.filter((e) => e[1].isVisible);
    }

    /** @returns {Object | undefined} the active page descriptor, if it has a Component */
    get page() {
        const entry = this.pages.find((e) => e[0] === this.state.currentPage);
        if (!entry) {
            return undefined;
        }
        const page = entry[1];
        return page.Component ? page : undefined;
    }

    /**
     * Switch to a page tab unless it is disabled or already active.
     * @param {string} pageIndex - page ID to activate
     */
    async activatePage(pageIndex) {
        // An id that matches no page would otherwise become `currentPage`,
        // leaving the notebook with no active tab and no rendered pane.
        const exists = this.pages.some(([id]) => id === pageIndex);
        if (
            !exists ||
            this.disabledPages.includes(pageIndex) ||
            this.state.currentPage === pageIndex
        ) {
            return;
        }
        const prom = (async () => this.props.onWillActivatePage(pageIndex))();
        const canProceed = await /** @type {KeepLast} */ (
            this.keepLastPageTransition
        ).add(prom);
        if (canProceed !== false) {
            this.state.currentPage = pageIndex;
        }
    }

    /**
     * Build the ordered page list from slots and programmatic pages.
     * @param {Object} props - component props with slots and/or pages
     * @returns {Array<[string, Object]>} ordered [id, descriptor] pairs
     */
    computePages(props) {
        // Initialised before the early return: `activatePage` reads it
        // unconditionally, so a notebook with neither slots nor pages used to
        // leave it undefined and throw on the first programmatic activation.
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
     * Determine which page should be active.
     * @param {string | undefined} defaultPage - preferred default page ID
     * @param {boolean} activateDefault - whether to force-activate the default
     * @returns {string | null} active page ID, or null if no pages exist
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

    /** Recompute the set of page IDs that contain invalid fields. */
    computeInvalidPages() {
        this.invalidPages = new Set();
        for (const page of this.navItems) {
            const invalid = page[1].fieldNames?.some((fieldName) =>
                this.env.model?.root.isFieldInvalid(fieldName),
            );
            if (invalid) {
                this.invalidPages.add(page[0]);
            }
        }
    }
}
