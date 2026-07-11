// @ts-check
/** @odoo-module native */

/** @module @web/components/emoji_picker/emoji_picker - Emoji picker with category navigation, fuzzy search, and recent emoji tracking */

import {
    App,
    Component,
    onMounted,
    onPatched,
    onWillDestroy,
    onWillRender,
    onWillStart,
    onWillUnmount,
    reactive,
    useComponent,
    useEffect,
    useExternalListener,
    useRef,
    useState,
    xml,
} from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { _t, appTranslateFn } from "@web/core/l10n/translation";
import { normalize } from "@web/core/l10n/utils";
import { getTemplate } from "@web/core/templates";
import { Deferred } from "@web/core/utils/concurrency";
import { markEventHandled } from "@web/core/utils/dom/events";
import { escapeRegExp } from "@web/core/utils/format/strings";
import { useAutofocus, useOwnedDialogs, useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
/**
 * @typedef Emoji
 * @property {string} category
 * @property {string} codepoints the emoji itself to be displayed
 * @property {string[]} emoticons string substitution (eg: ":p")
 * @property {string[]} keywords
 * @property {string} name
 * @property {string[]} shortcodes
 */
import { Dialog } from "@web/ui/dialog/dialog";
import { usePopover } from "@web/ui/popover/popover_hook";

export function useEmojiPicker(
    /** @type {any} */ ref,
    /** @type {any} */ props,
    /** @type {any} */ options,
) {
    return usePicker(EmojiPicker, ref, props, options);
}

/**
 * Precomputed, normalized fuzzy-search candidate strings per emoji. Rebuilding
 * these on every lookup dominated search cost over ~8.7k emojis; the emoji
 * objects are singletons, so build once here instead.
 *
 * @type {WeakMap<Emoji, string[]>}
 */
const searchStringsByEmoji = new WeakMap();

/**
 * @param {Emoji} emoji
 * @returns {string[]}
 */
function getEmojiSearchStrings(emoji) {
    let strings = searchStringsByEmoji.get(emoji);
    if (!strings) {
        strings = [
            emoji.name,
            ...emoji.keywords,
            ...emoji.emoticons,
            ...emoji.shortcodes,
        ].map(normalize);
        searchStringsByEmoji.set(emoji, strings);
    }
    return strings;
}

export const loader = reactive({
    loadEmoji: () => loadBundle("web.assets_emoji"),
    /** @type {{ emojiValueToShortcodes: {[key: string]: string[]}, emojiRegex: RegExp } | undefined} */
    loaded: undefined,
});

/** @returns {Promise<{ categories: any[], emojis: any[] }>} */
export async function loadEmoji() {
    /** @type {{ categories: any[], emojis: any[] }} */
    const res = { categories: [], emojis: [] };
    try {
        await loader.loadEmoji();
        const { getCategories, getEmojis } =
            await import("@web/components/emoji_picker/emoji_data");
        res.categories = getCategories();
        res.emojis = getEmojis();
        return res;
    } catch {
        // Could be intentional (tour ended successfully while emoji still loading)
        return res;
    } finally {
        if (!loader.loaded) {
            /** @type {{[key: string]: string[]}} */
            const emojiValueToShortcodes = {};
            for (const emoji of res.emojis) {
                emojiValueToShortcodes[emoji.codepoints] = emoji.shortcodes;
                // Precompute the normalized search strings once at data load.
                getEmojiSearchStrings(emoji);
            }
            loader.loaded = {
                emojiValueToShortcodes,
                emojiRegex: new RegExp(
                    Object.keys(emojiValueToShortcodes).length
                        ? Object.keys(emojiValueToShortcodes)
                              .map(escapeRegExp)
                              .sort((a, b) => b.length - a.length) // Sort to get composed emojis first
                              .join("|")
                        : /(?!)/,
                    "gu",
                ),
            };
        }
    }
}

export const PICKER_PROPS = [
    "PickerComponent?",
    "close?",
    "onClose?",
    "onSelect",
    "state?",
    "storeScroll?",
    "mobile?",
];

export class EmojiPicker extends Component {
    static props = [...PICKER_PROPS, "class?", "initialSearchTerm?"];
    static template = "web.EmojiPicker";

    // Declared with @type (not assigned) so strictNullChecks treats them as
    // initialized; setup()/onWillStart/onMounted assign them, and lifecycle
    // ordering guarantees they're non-undefined at every access site.
    /** @type {{el: HTMLElement | null}} */
    gridRef;
    /** @type {{el: HTMLElement | null}} */
    navbarRef;
    /** @type {any} */
    ui;
    /** @type {boolean} */
    isMobileOS;
    /** @type {{activeEmojiIndex: number, categoryId: number | null, searchTerm: string, hoveredEmoji: Emoji | undefined, emojiNavbarRepr: any[][] | undefined}} */
    state;
    /** @type {any} */
    frequentEmojiService;
    /** @type {{name: string, displayName: string, sortId: number, title?: string}[]} */
    categories;
    /** @type {Emoji[]} */
    emojis;
    /** @type {{[key: string]: Emoji}} */
    emojiByCodepoints;
    /** @type {Map<string, {name: string, displayName: string, sortId: number, title?: string}>} */
    categoryByName;
    // Search results are computed once per render (see onWillRender) and
    // cached non-reactively; the template reads the cached values through
    // recentEmojis / getEmojis().
    /** @type {Emoji[] | undefined} */
    _recentEmojis;
    /** @type {Emoji[] | undefined} */
    _emojis;
    // Fuzzy-search result cache for computeEmojis (see there).
    /** @type {string | undefined} */
    _emojisCacheKey;
    /** @type {Emoji[] | undefined} */
    _emojisCache;
    /** @type {{name: string, displayName: string, title: string, sortId: number}} */
    recentCategory;
    /** @type {ResizeObserver | undefined} */
    navbarResizeObserver;
    /** @type {boolean | (() => HTMLElement | null)} */
    shouldScrollElem = false;
    /** @type {string | undefined} */
    lastSearchTerm;
    keyboardNavigated = false;
    /** @type {any[]} */
    emojiMatrix;
    // searchTerm is a getter/setter pair (see below) — do not redeclare here.

    setup() {
        this.gridRef = useRef("emoji-grid");
        this.navbarRef = useRef("navbar");
        this.ui = useService("ui");
        this.isMobileOS = isMobileOS();
        this.state = useState({
            activeEmojiIndex: 0,
            categoryId: null,
            searchTerm: this.props.initialSearchTerm ?? "",
            /** @type {Emoji|undefined} */
            hoveredEmoji: undefined,
            /** @type {any[][] | undefined} */
            emojiNavbarRepr: undefined,
        });
        this.frequentEmojiService = useService("web.frequent.emoji");
        useAutofocus();
        onWillStart(async () => {
            const { categories, emojis } = await loadEmoji();
            this.categories = categories;
            this.emojis = emojis;
            this.emojiByCodepoints = Object.fromEntries(
                this.emojis.map((emoji) => [emoji.codepoints, emoji]),
            );
            this.categoryByName = new Map(
                this.categories.map((category) => [category.name, category]),
            );
            this.recentCategory = {
                name: "Frequently used",
                displayName: _t("Frequently used"),
                title: "🕓",
                sortId: 0,
            };
            this.state.categoryId = this.recentEmojis.length
                ? this.recentCategory.sortId
                : (this.categories[0]?.sortId ?? null);
        });
        onWillRender(() => {
            this._recentEmojis = this.computeRecentEmojis();
            this._emojis = this.computeEmojis();
        });
        onMounted(() => {
            if (!this.emojis.length) {
                return;
            }
            this.navbarResizeObserver = new ResizeObserver(() => this.adaptNavbar());
            this.navbarResizeObserver.observe(this.navbarRef.el);
            this.adaptNavbar();
            this.highlightActiveCategory();
            if (this.props.storeScroll) {
                this.gridRef.el.scrollTop = this.props.storeScroll.get();
            }
            this.state.hoveredEmoji = this.activeEmoji;
        });
        onPatched(() => {
            if (!this.emojis.length) {
                return;
            }
            if (this.shouldScrollElem) {
                this.shouldScrollElem = false;
                const getElement = () =>
                    this.gridRef.el.querySelector(
                        `.o-EmojiPicker-category[data-category="${this.state.categoryId}"]`,
                    );
                const elem = getElement();
                if (elem) {
                    elem.scrollIntoView();
                } else {
                    this.shouldScrollElem = getElement;
                }
            }
        });
        useEffect(
            () => this.updateEmojiPickerRepr(),
            () => [this.state.categoryId, this.state.searchTerm],
        );
        useEffect(
            (el) => {
                const gridEl = this.gridRef.el;
                const activeEl = gridEl?.querySelector(".o-Emoji.o-active");
                if (!gridEl) {
                    return;
                }
                if (
                    activeEl &&
                    this.keyboardNavigated &&
                    !isElementVisible(activeEl, gridEl)
                ) {
                    activeEl.scrollIntoView({
                        block: "center",
                        behavior: "instant",
                    });
                    this.keyboardNavigated = false;
                }
                this.state.hoveredEmoji = this.activeEmoji;
            },
            () => [this.state.activeEmojiIndex, this.gridRef.el],
        );
        useEffect(
            () => {
                if (!this.gridRef.el) {
                    return;
                }
                if (this.searchTerm) {
                    this.gridRef.el.scrollTop = 0;
                    this.state.categoryId = null;
                } else {
                    if (this.lastSearchTerm) {
                        this.gridRef.el.scrollTop = 0;
                    }
                    this.highlightActiveCategory();
                }
                this.lastSearchTerm = this.searchTerm;
            },
            () => [this.searchTerm],
        );
        onWillUnmount(() => {
            this.navbarResizeObserver?.disconnect();
            if (!this.gridRef.el) {
                return;
            }
            if (this.props.storeScroll) {
                this.props.storeScroll.set(this.gridRef.el.scrollTop);
            }
        });
    }

    adaptNavbar() {
        if (!this.navbarRef.el) {
            return;
        }
        const computedStyle = getComputedStyle(this.navbarRef.el);
        const availableWidth =
            this.navbarRef.el.getBoundingClientRect().width -
            Number.parseInt(computedStyle.paddingLeft, 10) -
            Number.parseInt(computedStyle.marginLeft, 10) -
            Number.parseInt(computedStyle.paddingRight, 10) -
            Number.parseInt(computedStyle.marginRight, 10);
        const itemWidth = this.navbarRef.el
            .querySelector(".o-Emoji")
            .getBoundingClientRect().width;
        const gapWidth = Number.parseInt(computedStyle.gap, 10);
        const maxAvailableNavbarItemAmountAtOnce = Math.floor(
            availableWidth / (itemWidth + gapWidth),
        );
        const repr = [];
        let panel = [];
        const allCategories = this.getAllCategories();
        for (const category of allCategories) {
            if (
                panel.length === maxAvailableNavbarItemAmountAtOnce - 1 &&
                category !== allCategories.at(-1)
            ) {
                panel.push("next");
                repr.push(panel);
                panel = [];
                panel.push("previous");
            }
            panel.push(category.sortId);
        }
        if (panel.length) {
            if (repr.length) {
                panel.push(
                    ...[
                        ...Array(maxAvailableNavbarItemAmountAtOnce - panel.length),
                    ].map((_, idx) => `empty_${idx}`),
                );
            }
            repr.push(panel);
        }
        this.state.emojiNavbarRepr = repr;
    }

    get currentNavbarPanel() {
        if (!this.state.emojiNavbarRepr) {
            return this.getAllCategories().map((c) => c.sortId);
        }
        if (this.state.categoryId === null || Number.isNaN(this.state.categoryId)) {
            return this.state.emojiNavbarRepr[0];
        }
        return this.state.emojiNavbarRepr.find((panel) =>
            panel.includes(this.state.categoryId),
        );
    }

    get searchTerm() {
        return this.props.state ? this.props.state.searchTerm : this.state.searchTerm;
    }

    set searchTerm(value) {
        if (this.props.state) {
            this.props.state.searchTerm = value;
        } else {
            this.state.searchTerm = value;
        }
    }

    get recentEmojis() {
        return this._recentEmojis ?? this.computeRecentEmojis();
    }

    computeRecentEmojis() {
        const recent = Object.entries(this.frequentEmojiService.all)
            .sort(([, usage_1], [, usage_2]) => usage_2 - usage_1)
            .map(([codepoints]) => this.emojiByCodepoints[codepoints])
            // Persisted codepoints may no longer exist after an emoji data update.
            .filter(Boolean);
        if (this.searchTerm && recent.length) {
            return fuzzyLookup(this.searchTerm, recent, getEmojiSearchStrings);
        }
        return recent.slice(0, 42);
    }

    get placeholder() {
        return this.state.hoveredEmoji?.shortcodes.join(" ") ?? _t("Search emoji");
    }

    onMouseenterEmoji(ev, emoji) {
        this.state.hoveredEmoji = emoji;
    }

    onMouseleaveEmoji(ev, emoji) {
        this.state.hoveredEmoji = this.activeEmoji;
    }

    onClick(ev) {
        markEventHandled(ev, "emoji.selectEmoji");
    }

    onClickToNextCategories() {
        const panelIndex = this.state.emojiNavbarRepr.findIndex((p) =>
            p.includes(this.state.categoryId),
        );
        const nextPanel =
            panelIndex === -1 ? undefined : this.state.emojiNavbarRepr[panelIndex + 1];
        if (!nextPanel) {
            return;
        }
        this.selectCategory(nextPanel[1]);
    }

    onClickToPreviousCategories() {
        const panelIndex = this.state.emojiNavbarRepr.findIndex((p) =>
            p.includes(this.state.categoryId),
        );
        if (panelIndex <= 0) {
            return;
        }
        this.selectCategory(this.state.emojiNavbarRepr[panelIndex - 1].at(-2));
    }

    /**
     * Builds a 2D matrix of emoji indices from the current DOM, used for
     * keyboard navigation.
     */
    updateEmojiPickerRepr() {
        if (!this.emojis.length) {
            return;
        }
        const emojiEls = Array.from(this.gridRef.el.querySelectorAll(".o-Emoji"));
        const emojiRects = emojiEls.map((el) => el.getBoundingClientRect());
        this.emojiMatrix = [];
        for (const [index, pos] of emojiRects.entries()) {
            const emojiIndex = emojiEls[index].dataset.index;
            if (!this.emojiMatrix.length || pos.top > emojiRects[index - 1].top) {
                this.emojiMatrix.push([]);
            }
            this.emojiMatrix.at(-1).push(Number.parseInt(emojiIndex, 10));
        }
    }

    handleNavigation(key) {
        const currentIdx = this.state.activeEmojiIndex;
        let currentRow = -1;
        let currentCol = -1;
        const rowIdx = this.emojiMatrix.findIndex((row) => row.includes(currentIdx));
        if (rowIdx !== -1) {
            currentRow = rowIdx;
            currentCol = this.emojiMatrix[currentRow].indexOf(currentIdx);
        }
        let newIdx;
        switch (key) {
            case "ArrowDown": {
                const rowBelow = this.emojiMatrix[currentRow + 1];
                const rowBelowBelow = this.emojiMatrix[currentRow + 2];
                if (
                    rowBelow?.length <= currentCol &&
                    rowBelowBelow?.length >= currentCol
                ) {
                    newIdx = rowBelowBelow?.[currentCol];
                } else {
                    newIdx = rowBelow?.[Math.min(currentCol, rowBelow.length - 1)];
                }
                break;
            }
            case "ArrowUp": {
                const rowAbove = this.emojiMatrix[currentRow - 1];
                const rowAboveAbove = this.emojiMatrix[currentRow - 2];
                if (
                    rowAbove?.length <= currentCol &&
                    rowAboveAbove?.length >= currentCol
                ) {
                    newIdx = rowAboveAbove?.[currentCol];
                } else {
                    newIdx = rowAbove?.[Math.min(currentCol, rowAbove.length - 1)];
                }
                break;
            }
            case "ArrowRight": {
                const colRight = currentCol + 1;
                if (colRight === this.emojiMatrix[currentRow]?.length) {
                    const rowBelowRight = this.emojiMatrix[currentRow + 1];
                    newIdx = rowBelowRight?.[0];
                } else {
                    newIdx = this.emojiMatrix[currentRow]?.[colRight];
                }
                break;
            }
            case "ArrowLeft": {
                const colLeft = currentCol - 1;
                if (colLeft < 0) {
                    const rowAboveLeft = this.emojiMatrix[currentRow - 1];
                    newIdx = rowAboveLeft?.at(-1) ?? this.state.activeEmojiIndex;
                } else {
                    newIdx = this.emojiMatrix[currentRow][colLeft];
                }
                break;
            }
        }
        this.state.activeEmojiIndex = newIdx ?? this.state.activeEmojiIndex;
    }

    get activeEmoji() {
        const activeCodepoints = this.gridRef.el.querySelector(
            `.o-EmojiPicker-content .o-Emoji[data-index="${this.state.activeEmojiIndex}"]`,
        )?.dataset.codepoints;
        return activeCodepoints ? this.emojiByCodepoints[activeCodepoints] : undefined;
    }

    onKeydown(ev) {
        switch (ev.key) {
            case "ArrowDown":
            case "ArrowUp":
            case "ArrowRight":
            case "ArrowLeft":
                this.handleNavigation(ev.key);
                this.keyboardNavigated = true;
                break;
            case "Enter":
                ev.preventDefault();
                this.gridRef.el
                    ?.querySelector(
                        `.o-EmojiPicker-content .o-Emoji[data-index="${this.state.activeEmojiIndex}"]`,
                    )
                    ?.click();
                break;
            case "Escape":
                // close() is responsible for notifying onClose (usePicker wires
                // it through the popover/dialog close path); calling both here
                // fired the consumer's onClose twice.
                this.props.close?.();
                ev.stopPropagation();
        }
    }

    getAllCategories() {
        const res = [...this.categories];
        if (this.recentEmojis.length) {
            res.unshift(this.recentCategory);
        }
        return res;
    }

    getEmojis() {
        return this._emojis ?? this.computeEmojis();
    }

    computeEmojis() {
        const recentEmojis = this.recentEmojis;
        // Fuzzy search over ~8.7k emojis is costly; without caching it would
        // re-run on every render, including hover renders. Key the cache on
        // everything it depends on: search term and excluded recent emojis.
        const cacheKey = this.searchTerm
            ? `${this.searchTerm}\x00${recentEmojis.map((e) => e.codepoints).join(",")}`
            : "";
        if (this._emojisCache && this._emojisCacheKey === cacheKey) {
            return this._emojisCache;
        }
        let emojisToDisplay = [...this.emojis];
        if (recentEmojis.length && this.searchTerm) {
            emojisToDisplay = emojisToDisplay.filter(
                (emoji) => !recentEmojis.includes(emoji),
            );
        }
        if (this.searchTerm.length) {
            emojisToDisplay = fuzzyLookup(
                this.searchTerm,
                emojisToDisplay,
                getEmojiSearchStrings,
            );
        }
        this._emojisCacheKey = cacheKey;
        this._emojisCache = emojisToDisplay;
        return emojisToDisplay;
    }

    getEmojisFromSearch() {
        return [...this.recentEmojis, ...this.getEmojis()];
    }

    selectCategory(categoryId) {
        this.searchTerm = "";
        this.state.categoryId = categoryId;
        this.shouldScrollElem = true;
    }

    selectEmoji(ev) {
        const codepoints = ev.currentTarget.dataset.codepoints;
        let resetOnSelect = !ev.shiftKey;
        const res = this.props.onSelect(codepoints, resetOnSelect);
        if (res === false) {
            resetOnSelect = false;
        }
        this.frequentEmojiService.incrementEmojiUsage(codepoints);
        if (resetOnSelect) {
            this.gridRef.el.scrollTop = 0;
            this.props.close?.();
        }
    }

    highlightActiveCategory() {
        if (!this.gridRef || !this.gridRef.el) {
            return;
        }
        const coords = this.gridRef.el.getBoundingClientRect();
        const res = document.elementFromPoint(coords.x + 10, coords.y + 10);
        if (!res) {
            return;
        }
        this.state.categoryId = Number.parseInt(
            /** @type {HTMLElement} */ (res).dataset.category,
            10,
        );
    }
}

/**
 * @param {import("@odoo/owl").ComponentConstructor} PickerComponent
 * @param {{ el: HTMLElement | null }} ref
 * @param {Record<string, any>} props
 * @param {Record<string, any>} [options]
 */
export function usePicker(PickerComponent, ref, props, options = {}) {
    const component = useComponent();
    const targets = [];
    const state = useState({ isOpen: false });
    const ui = useService("ui");
    const addDialog = useOwnedDialogs();
    let remove;
    const newOptions = {
        ...options,
        onClose: () => {
            state.isOpen = false;
            props.onClose?.();
        },
    };
    const popover = usePopover(/** @type {any} */ (PickerComponent), {
        ...newOptions,
        animation: false,
        popoverClass: (options.popoverClass ?? "") + " bg-100 border border-secondary",
    });
    // Local session object (not written into the caller's props): keeps the
    // grid scroll position across open/close cycles of the same picker.
    const storeScroll = {
        scrollValue: 0,
        set: (value) => {
            storeScroll.scrollValue = value;
        },
        get: () => storeScroll.scrollValue,
    };

    /**
     * @param {import("@web/core/utils/hooks").Ref} ref
     */
    function add(ref, onSelect, { show = false } = {}) {
        const toggler = () => toggle(isMobileOS() ? undefined : ref, onSelect);
        targets.push([ref, toggler]);
        if (!ref.el) {
            return;
        }
        ref.el.addEventListener("click", toggler);
        ref.el.addEventListener("mouseenter", loadEmoji);
        if (show) {
            ref.el.click();
        }
    }

    function open(ref, openProps) {
        state.isOpen = true;
        if (ui.isSmall || isMobileOS()) {
            const def = new Deferred();
            const pickerMobileProps = {
                PickerComponent,
                onSelect: (...args) => {
                    const func = openProps?.onSelect ?? props?.onSelect;
                    const res = func?.(...args);
                    def.resolve(true);
                    return res;
                },
            };
            if (ref?.el) {
                pickerMobileProps.close = () => remove?.();
                const app = new App(
                    PickerMobile,
                    /** @type {any} */ ({
                        name: "Popout",
                        env: component.env,
                        props: pickerMobileProps,
                        getTemplate,
                        translatableAttributes: ["data-tooltip"],
                        translateFn: appTranslateFn,
                    }),
                );
                app.mount(ref.el);
                remove = () => {
                    remove = null;
                    state.isOpen = false;
                    props.onClose?.();
                    app.destroy();
                };
            } else {
                /** @type {any} */
                const dialogOptions = {
                    context: component,
                    onClose: () => {
                        remove = null;
                        state.isOpen = false;
                        props.onClose?.();
                        return def.resolve(false);
                    },
                };
                const closeDialog = addDialog(
                    PickerMobileInDialog,
                    pickerMobileProps,
                    dialogOptions,
                );
                remove = () => closeDialog();
            }
            return def;
        }
        return popover.open(ref.el, { ...props, storeScroll, ...openProps });
    }

    function close() {
        remove?.();
        popover.close?.();
    }

    function toggle(ref, onSelect = props.onSelect) {
        if (state.isOpen) {
            close();
        } else {
            open(ref, { ...props, onSelect });
        }
    }

    if (ref) {
        add(ref);
    }
    // Rebind the toggler listeners only when a target element actually
    // changes identity, instead of removing/re-adding them on every patch.
    useEffect(
        () => {
            const attached = [];
            for (const [ref, toggler] of targets) {
                if (!ref.el) {
                    continue;
                }
                ref.el.addEventListener("click", toggler);
                ref.el.addEventListener("mouseenter", loadEmoji);
                attached.push([ref.el, toggler]);
            }
            return () => {
                for (const [el, toggler] of attached) {
                    el.removeEventListener("click", toggler);
                    el.removeEventListener("mouseenter", loadEmoji);
                }
            };
        },
        () => targets.map(([ref]) => ref.el),
    );
    // The mobile picker is a standalone App / dialog: tear it down with its
    // owner, else it survives the owner's destruction.
    onWillDestroy(() => remove?.());
    Object.assign(state, { open, close, toggle });
    return state;
}

class PickerMobile extends Component {
    static props = [...PICKER_PROPS, "onClose?"];
    static template = xml`
        <t t-component="props.PickerComponent" t-props="pickerProps"/>
    `;

    get pickerProps() {
        return {
            ...this.props,
            onSelect: (...args) => this.props.onSelect(...args),
            mobile: true,
        };
    }
}

class PickerMobileInDialog extends PickerMobile {
    static components = { Dialog };
    static props = [...PICKER_PROPS, "onClose?"];
    static template = xml`
        <Dialog size="'lg'" header="false" footer="false" contentClass="'o-discuss-mobileContextMenu d-flex position-absolute bottom-0 rounded-0 h-50 bg-100'" bodyClass="'p-1'">
            <div class="h-100" t-ref="root">
                <t t-component="props.PickerComponent" t-props="pickerProps"/>
            </div>
        </Dialog>
    `;

    setup() {
        super.setup();
        this.root = useRef("root");
        useExternalListener(
            window,
            "click",
            (ev) => {
                if (
                    ev.target !== this.root.el &&
                    !this.root.el.contains(/** @type {Node} */ (ev.target))
                ) {
                    this.props.close?.();
                }
            },
            { capture: true },
        );
    }
}

function isElementVisible(el, holder) {
    const offset = 20;
    holder = holder || document.body;
    const { top, bottom, height } = el.getBoundingClientRect();
    let { top: holderTop, bottom: holderBottom } = holder.getBoundingClientRect();
    holderTop += offset * 2; // section are position sticky top so emoji can be "visible" under section name. Overestimate to assume invisible.
    holderBottom -= offset;
    return top - offset <= holderTop
        ? holderTop - top <= height
        : bottom - holderBottom <= height;
}
