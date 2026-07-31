// @ts-check
/** @odoo-module native */

/** @module @web/components/autocomplete/autocomplete */

import {
    Component,
    onMounted,
    onWillDestroy,
    onWillUpdateProps,
    useRef,
    useState,
} from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { reportUncaught } from "@web/core/errors/error_utils";
import { usePosition } from "@web/core/position/position_hook";
import { Deferred } from "@web/core/utils/concurrency";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { useClickAway } from "@web/core/utils/dom/click_away";
import { isScrollableY, scrollTo } from "@web/core/utils/dom/scrolling";
import { uniqueId } from "@web/core/utils/functions";
import { useAutofocus, useForwardRefToParent } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

export class AutoComplete extends Component {
    static template = "web.AutoComplete";
    static props = {
        value: { type: String, optional: true },
        id: { type: String, optional: true },
        sources: {
            type: Array,
            element: {
                type: Object,
                shape: {
                    placeholder: { type: String, optional: true },
                    options: [Array, Function],
                    optionSlot: { type: String, optional: true },
                },
            },
        },
        placeholder: { type: String, optional: true },
        title: { type: String, optional: true },
        autocomplete: { type: String, optional: true },
        autoSelect: { type: Boolean, optional: true },
        resetOnSelect: { type: Boolean, optional: true },
        onInput: { type: Function, optional: true },
        onCancel: { type: Function, optional: true },
        onChange: { type: Function, optional: true },
        onBlur: { type: Function, optional: true },
        onFocus: { type: Function, optional: true },
        searchOnInputClick: { type: Boolean, optional: true },
        input: { type: Function, optional: true },
        inputDebounceDelay: { type: Number, optional: true },
        dropdown: { type: Boolean, optional: true },
        autofocus: { type: Boolean, optional: true },
        class: { type: String, optional: true },
        slots: { type: Object, optional: true },
        menuPositionOptions: { type: Object, optional: true },
        menuCssClass: { type: [String, Array, Object], optional: true },
        selectOnBlur: { type: Boolean, optional: true },
    };
    static defaultProps = {
        value: "",
        placeholder: "",
        title: "",
        autocomplete: "new-password",
        autoSelect: false,
        dropdown: true,
        onInput: () => {},
        onCancel: () => {},
        onChange: () => {},
        onBlur: () => {},
        onFocus: () => {},
        searchOnInputClick: true,
        inputDebounceDelay: 250,
        menuPositionOptions: {},
        menuCssClass: {},
    };

    get timeout() {
        return this.props.inputDebounceDelay;
    }

    setup() {
        this.autoCompleteId = uniqueId("autocomplete_");
        this.nextSourceId = 0;
        this.nextOptionId = 0;
        this._loadId = 0;
        this.inEdition = false;
        this.mouseSelectionActive = false;
        this.isOptionSelected = false;

        this.state = useState({
            navigationRev: 0,
            open: false,
            activeSourceOption: null,
            value: this.props.value,
            /** @type {any[]} */
            sources: [],
        });

        this.inputRef = /** @type {any} */ (useForwardRefToParent("input"));
        this.listRef = useRef("sourcesList");
        if (this.props.autofocus) {
            useAutofocus({ refName: "input" });
        }
        this.root = useRef("root");

        this.debouncedProcessInput = useDebounced(
            async () => {
                const currentPromise = this.pendingPromise;
                this.pendingPromise = null;
                this.props.onInput({
                    inputValue: this.inputRef.el.value,
                });
                try {
                    await this.open(true);
                    currentPromise.resolve();
                } catch (error) {
                    currentPromise.reject(error);
                } finally {
                    if (currentPromise === this.loadingPromise) {
                        this.loadingPromise = null;
                    }
                }
            },
            () => this.timeout,
        );

        useClickAway((node) => this.externalClose(node), {
            getAnchor: () => this.root.el,
            getContentEl: () => this.listRef.el,
        });
        this._onScrollAway = (/** @type {Event} */ ev) =>
            this.externalClose(/** @type {Node} */ (ev.target));
        this._onMouseMove = () => {
            this._mouseMoveCleanup = null;
            this.mouseSelectionActive = true;
        };
        this._globalCleanups = [];
        this._mouseMoveCleanup = null;
        onWillDestroy(() => this._removeGlobalListeners());

        onWillUpdateProps((nextProps) => {
            if (this.props.value !== nextProps.value || this.forceValFromProp) {
                this.forceValFromProp = false;
                if (!this.inEdition) {
                    this.state.value = nextProps.value;
                    this.inputRef.el.value = nextProps.value;
                }
                this.close();
            }
        });

        if (this.props.dropdown) {
            usePosition("sourcesList", () => this.targetDropdown, this.dropdownOptions);
        } else {
            this.state.open = true;
            this.loadSources(false);
            onMounted(() => {
                if (this.state.open) {
                    this._addGlobalListeners();
                }
            });
        }
    }

    get targetDropdown() {
        return this.inputRef.el;
    }

    get sources() {
        return this.state.sources;
    }

    /** @type {string} */
    get idPrefix() {
        return this.props.id || this.autoCompleteId;
    }

    get activeSourceOptionId() {
        if (!this.isOpened || !this.state.activeSourceOption) {
            return undefined;
        }
        const [sourceIndex, optionIndex] = this.state.activeSourceOption;
        const source = this.sources[sourceIndex];
        return `${this.idPrefix}_${sourceIndex}_${
            source.isLoading ? "loading" : optionIndex
        }`;
    }

    get dropdownOptions() {
        return {
            position: "bottom-start",
            ...this.props.menuPositionOptions,
        };
    }

    get isOpened() {
        return this.state.open;
    }

    get hasOptions() {
        for (const source of this.sources) {
            if (source.isLoading || source.options.length) {
                return true;
            }
        }
        return false;
    }

    get activeOption() {
        if (!this.state.activeSourceOption) {
            return null;
        }
        const [sourceIndex, optionIndex] = this.state.activeSourceOption;
        return this.sources[sourceIndex].options[optionIndex];
    }

    open(useInput = false) {
        this.state.open = true;
        this._addGlobalListeners();
        return this.loadSources(useInput);
    }

    close() {
        this.state.open = false;
        this.state.activeSourceOption = null;
        // Tab only commits a suggestion the user actually browsed to. That is a
        // fact about the open dropdown, so it dies with it.
        this.state.navigationRev = 0;
        this._loadId++;
        this.debouncedProcessInput.cancel();
        this.pendingPromise?.resolve();
        this.pendingPromise = null;
        this.loadingPromise = null;
        this._resetMouseSelection();
        this._removeGlobalListeners();
    }

    _addGlobalListeners() {
        if (this._globalCleanups.length) {
            return;
        }
        const add = (target, event, handler, capture = false) => {
            target.addEventListener(event, handler, capture);
            this._globalCleanups.push(() =>
                target.removeEventListener(event, handler, capture),
            );
        };
        add(window, "scroll", this._onScrollAway, true);
        this._armMouseMove();
    }

    _removeGlobalListeners() {
        for (const cleanup of this._globalCleanups) {
            cleanup();
        }
        this._globalCleanups = [];
        this._mouseMoveCleanup?.();
        this._mouseMoveCleanup = null;
    }

    _armMouseMove() {
        if (this._mouseMoveCleanup) {
            return;
        }
        window.addEventListener("mousemove", this._onMouseMove, {
            capture: true,
            once: true,
        });
        this._mouseMoveCleanup = () =>
            window.removeEventListener("mousemove", this._onMouseMove, {
                capture: true,
            });
    }

    _resetMouseSelection() {
        this.mouseSelectionActive = false;
        if (this.isOpened) {
            this._armMouseMove();
        }
    }

    cancel() {
        if (this.inputRef.el.value.length) {
            if (this.props.autoSelect) {
                this.inputRef.el.value = this.props.value;
                this.props.onCancel();
            }
        }
        this.inEdition = false;
        this.close();
    }

    /**
     * @param {boolean} useInput
     */
    async loadSources(useInput) {
        const loadId = ++this._loadId;
        const request = useInput ? this.inputRef.el.value.trim() : null;
        this.state.sources = this.props.sources.map((pSource) =>
            this.makeSource(pSource),
        );
        this.state.activeSourceOption = null;

        const proms = [];
        for (const [index, pSource] of this.props.sources.entries()) {
            const source = this.state.sources[index];
            const options = this.loadOptions(pSource.options, request ?? "");
            if (options instanceof Promise) {
                source.isLoading = true;
                proms.push(
                    options.then(
                        (options) => {
                            if (loadId !== this._loadId) {
                                return;
                            }
                            source.options = options.map((option) =>
                                this.makeOption(option),
                            );
                            source.isLoading = false;
                        },
                        (error) => {
                            if (loadId !== this._loadId) {
                                return;
                            }
                            source.isLoading = false;
                            this.reportSourceError(error);
                        },
                    ),
                );
            } else {
                source.options = options.map((option) => this.makeOption(option));
            }
        }

        await Promise.all(proms);
        if (loadId !== this._loadId) {
            return;
        }
        this._loadedRequest = request;
        this.navigate(0);
        this.scroll();
    }

    /**
     * @param {any} error
     */
    reportSourceError(error) {
        reportUncaught(error);
    }
    get displayOptions() {
        return !this.props.dropdown || (this.isOpened && this.hasOptions);
    }
    loadOptions(options, request) {
        if (typeof options === "function") {
            return options(request);
        } else {
            return options;
        }
    }
    makeOption(option) {
        return {
            cssClass: "",
            data: {},
            ...option,
            id: ++this.nextOptionId,
            unselectable: !option.onSelect,
        };
    }
    makeSource(source) {
        return {
            id: ++this.nextSourceId,
            options: [],
            isLoading: false,
            placeholder: source.placeholder,
            optionSlot: source.optionSlot,
        };
    }

    isActiveSourceOption([sourceIndex, optionIndex]) {
        return (
            this.state.activeSourceOption &&
            this.state.activeSourceOption[0] === sourceIndex &&
            this.state.activeSourceOption[1] === optionIndex
        );
    }

    selectOption(option) {
        this.inEdition = false;
        if (!option || option.unselectable) {
            return;
        }

        if (this.props.resetOnSelect) {
            this.inputRef.el.value = "";
        }
        this.isOptionSelected = true;
        this.forceValFromProp = true;
        option.onSelect();
        this.close();
    }

    /**
     * Every option the user can actually land on, in display order. Sources
     * still loading contribute nothing: they have no options yet.
     *
     * @returns {Array<[number, number]>}
     */
    get selectablePositions() {
        const positions = [];
        for (const [sourceIndex, source] of this.sources.entries()) {
            if (source.isLoading) {
                continue;
            }
            for (const [optionIndex, option] of source.options.entries()) {
                if (!option.unselectable) {
                    positions.push([sourceIndex, optionIndex]);
                }
            }
        }
        return positions;
    }

    /**
     * Moves the active option one selectable step, without wrapping: stepping
     * off either end clears the selection, and the next step in the same
     * direction re-enters from the opposite end. A direction of 0 resets to the
     * first selectable option, which is what a fresh source load wants.
     *
     * @param {number} direction
     */
    navigate(direction) {
        this._resetMouseSelection();
        const positions = this.selectablePositions;
        const step = Math.sign(direction);
        if (!step) {
            this.state.activeSourceOption = positions[0] ?? null;
            return;
        }
        this.state.navigationRev++;

        const active = this.state.activeSourceOption;
        const activeIndex = active
            ? positions.findIndex(
                  ([sourceIndex, optionIndex]) =>
                      sourceIndex === active[0] && optionIndex === active[1],
              )
            : -1;
        let nextIndex;
        if (activeIndex === -1) {
            nextIndex = step > 0 ? 0 : positions.length - 1;
        } else {
            nextIndex = activeIndex + step;
        }
        this.state.activeSourceOption = positions[nextIndex] ?? null;
    }

    onInputBlur() {
        if (this.ignoreBlur) {
            this.ignoreBlur = false;
            return;
        }
        if (this.props.selectOnBlur && !this.isOptionSelected && !this.loadingPromise) {
            this.state.activeSourceOption = this.selectablePositions[0] ?? null;
            if (this.activeOption) {
                this.selectOption(this.activeOption);
            }
        }
        this.props.onBlur({
            inputValue: this.inputRef.el.value,
        });
        this.inEdition = false;
        this.isOptionSelected = false;
    }
    onInputClick() {
        if (!this.isOpened && this.props.searchOnInputClick) {
            this.open(this.inputRef.el.value.trim() !== this.props.value.trim());
        } else {
            this.close();
        }
    }
    onInputChange(ev) {
        if (this.ignoreBlur) {
            ev.stopImmediatePropagation();
        }
        this.props.onChange({
            inputValue: this.inputRef.el.value,
            isOptionSelected: this.ignoreBlur,
        });
    }
    async onInput() {
        this.inEdition = true;
        if (!this.pendingPromise) {
            this.pendingPromise = new Deferred();
            this.pendingPromise.catch(() => {});
        }
        this.loadingPromise = this.pendingPromise;
        this.debouncedProcessInput();
    }

    onInputFocus(ev) {
        this.inputRef.el.setSelectionRange(0, this.inputRef.el.value.length);
        this.props.onFocus(ev);
    }

    get autoCompleteRootClass() {
        let classList = "";
        if (this.props.class) {
            classList += this.props.class;
        }
        if (this.props.dropdown) {
            classList += " dropdown";
        }
        return classList;
    }

    get ulDropdownClass() {
        return mergeClasses(this.props.menuCssClass, {
            "dropdown-menu ui-autocomplete": this.props.dropdown,
            "list-group": !this.props.dropdown,
        });
    }

    async onInputKeydown(ev) {
        const hotkey = getActiveHotkey(ev);
        const isSelectKey = hotkey === "enter" || hotkey === "tab";

        if (this.loadingPromise && isSelectKey) {
            if (hotkey === "enter") {
                ev.stopPropagation();
                ev.preventDefault();
            }

            try {
                await this.loadingPromise;
            } catch {}
        }

        switch (hotkey) {
            case "enter":
                if (!this.isOpened || !this.state.activeSourceOption) {
                    return;
                }
                this.selectOption(this.activeOption);
                break;
            case "escape":
                if (!this.isOpened) {
                    return;
                }
                this.cancel();
                break;
            case "tab":
            case "shift+tab":
                if (!this.isOpened) {
                    return;
                }
                if (
                    this.props.autoSelect &&
                    this.state.activeSourceOption &&
                    (this.state.navigationRev > 0 || this.inputRef.el.value.length)
                ) {
                    this.selectOption(this.activeOption);
                }
                this.close();
                return;
            case "arrowup":
                this.navigate(-1);
                if (!this.isOpened) {
                    this.open(true);
                }
                this.scroll();
                break;
            case "arrowdown":
                this.navigate(+1);
                if (!this.isOpened) {
                    this.open(true);
                }
                this.scroll();
                break;
            default:
                return;
        }

        ev.stopPropagation();
        ev.preventDefault();
    }

    onOptionMouseEnter(indices) {
        if (!this.mouseSelectionActive) {
            return;
        }

        const [sourceIndex, optionIndex] = indices;
        if (this.sources[sourceIndex].options[optionIndex]?.unselectable) {
            this.state.activeSourceOption = null;
        } else {
            this.state.activeSourceOption = indices;
        }
    }
    onOptionMouseLeave() {
        if (!this.mouseSelectionActive) {
            return;
        }
        this.state.activeSourceOption = null;
    }
    async onOptionClick(option) {
        const staleOptions =
            typeof this._loadedRequest === "string" &&
            this._loadedRequest !== this.inputRef.el.value.trim();
        if (staleOptions) {
            try {
                await this.loadingPromise;
            } catch {}
            this.inputRef.el.focus();
            return;
        }
        this.selectOption(option);
        this.inputRef.el.focus();
    }
    onOptionPointerDown(option, ev) {
        if (option.unselectable) {
            ev.preventDefault();
            return;
        }
        this.ignoreBlur = true;
    }

    /** @param {Node} [node] */
    externalClose(node) {
        if (this.isOpened && !this.root.el?.contains(node ?? null)) {
            this.cancel();
        }
    }

    scroll() {
        if (!this.activeSourceOptionId) {
            return;
        }
        if (isScrollableY(this.listRef.el)) {
            const element = this.listRef.el.querySelector(
                `#${CSS.escape(this.activeSourceOptionId)}`,
            );
            if (element) {
                scrollTo(element);
            }
        }
    }
}
