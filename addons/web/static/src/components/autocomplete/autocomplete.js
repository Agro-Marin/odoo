// @ts-check
/** @odoo-module native */

/** @module @web/components/autocomplete/autocomplete */

import {
    Component,
    onMounted,
    onWillDestroy,
    onWillRender,
    onWillUpdateProps,
    useRef,
    useState,
} from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { reportUncaught } from "@web/core/errors/error_utils";
import { useNavigation } from "@web/core/navigation/navigation";
import { usePosition } from "@web/core/position/position_hook";
import { Deferred, KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { useClickAway } from "@web/core/utils/dom/click_away";
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
        this.inEdition = false;
        this.isOptionSelected = false;
        this.dismissed = false;

        // Tab only commits a suggestion the user actually browsed to. That is
        // a fact about the open dropdown, so close() resets it. Not state: no
        // render depends on it.
        this.navigationRev = 0;

        // One load owns the dropdown at a time; superseding it (a newer load,
        // or close()) rejects the superseded tail with a SupersededError so
        // every caller awaiting a load still settles.
        this.keepLast = new KeepLast({ rejectSuperseded: true });

        /**
         * A finished load's pending "present the options" step: the entry
         * activation must land on the freshly rendered list, so it runs on
         * the navigator update that follows the render (onNavigationUpdated)
         * and resolves `applied` once it has.
         *
         * @type {{ direction: number, applied: Deferred<void> } | null}
         */
        this._entry = null;

        this.state = useState({
            open: false,
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

        this.navigator = useNavigation(this.root, {
            virtualFocus: true,
            wrap: false,
            activeClass: "ui-state-active",
            mouseActivation: "armed",
            shouldFocusChildInput: false,
            shouldRegisterHotkeys: false,
            getItems: () =>
                /** @type {any} */ (
                    this.root.el?.querySelectorAll(
                        ":scope .o-autocomplete--dropdown-item > a.ui-menu-item-wrapper",
                    ) ?? []
                ),
            getHoverTarget: (el) =>
                /** @type {HTMLElement} */ (
                    el.closest(".o-autocomplete--dropdown-item") ?? el
                ),
            onUpdated: () => this.onNavigationUpdated(),
        });

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
        this._globalCleanups = [];
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
            this._dropdownOptions = {};
            this.syncDropdownOptions();
            onWillRender(() => this.syncDropdownOptions());
            usePosition(
                "sourcesList",
                () => this.targetDropdown,
                this._dropdownOptions,
            );
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

    /** @returns {[number, number] | null} the [source, option] indices of the
     *  navigator's active item, read off the option element's own id -- the
     *  navigator owns the cursor, the component only translates it back into
     *  its data space. */
    get activeSourceOption() {
        const el = this.navigator.activeItem?.el;
        const match = el && /_(\d+)_(\d+)$/.exec(el.id);
        return match ? [Number(match[1]), Number(match[2])] : null;
    }

    /** @returns {boolean} */
    get isLoadingSources() {
        return this.sources.some((source) => source.isLoading);
    }

    /** @returns {Record<string, any>} */
    get dropdownOptions() {
        return {
            position: "bottom-start",
            ...this.props.menuPositionOptions,
        };
    }

    /**
     * usePosition keeps the object it is handed and re-reads it on every
     * reposition, so what it holds has to be one object for the component's
     * whole life -- `dropdownOptions` yields a fresh merge each call, and
     * subclasses override it to yield another. Refreshing that one object's
     * contents from the getter is what lets both stay live.
     */
    syncDropdownOptions() {
        const live = /** @type {Record<string, any>} */ (this._dropdownOptions);
        for (const key of Object.keys(live)) {
            delete live[key];
        }
        Object.assign(live, this.dropdownOptions);
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
        const el = this.navigator.activeItem?.el;
        return el ? this._optionForElement(el) : null;
    }

    /**
     * Translates an option element back into the option it renders, through
     * the `{idPrefix}_{sourceIndex}_{optionIndex}` id the template stamps on
     * every option.
     *
     * @param {HTMLElement} el
     * @returns {any | null}
     */
    _optionForElement(el) {
        const match = /_(\d+)_(\d+)$/.exec(el.id);
        if (!match) {
            return null;
        }
        return this.sources[Number(match[1])]?.options[Number(match[2])] ?? null;
    }

    /**
     * @param {boolean} [useInput]
     * @param {number} [entryDirection] which end of the loaded list to land on:
     *  -1 for the last option, anything else for the first.
     */
    open(useInput = false, entryDirection = 0) {
        this.state.open = true;
        this.dismissed = false;
        this._addGlobalListeners();
        return this.loadSources(useInput, entryDirection);
    }

    close() {
        this.state.open = false;
        this.navigator.clearActiveItem();
        // Tab only commits a suggestion the user actually browsed to. That is a
        // fact about the open dropdown, so it dies with it.
        this.navigationRev = 0;
        // Abandon any in-flight load: its tail is rejected with a
        // SupersededError and returns quietly, so its awaiters still settle.
        this.keepLast.cancel();
        if (this._entry) {
            this._entry.applied.resolve();
            this._entry = null;
        }
        this.debouncedProcessInput.cancel();
        this.pendingPromise?.resolve();
        this.pendingPromise = null;
        this.loadingPromise = null;
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
    }

    _removeGlobalListeners() {
        for (const cleanup of this._globalCleanups) {
            cleanup();
        }
        this._globalCleanups = [];
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
     * @param {number} [entryDirection] @see open
     */
    async loadSources(useInput, entryDirection = 0) {
        // The text the box held when these options were asked for. Unlike
        // `request` it is recorded even for a load that ignores the input, so
        // it can answer "are these still the suggestions for what is on
        // screen?" in every case. Read here rather than after the await: the
        // inline variant loads before it is mounted, and any load can outlive
        // the input it started from.
        const inputValue = this.inputRef.el?.value.trim() ?? "";
        const request = useInput ? inputValue : null;
        this.state.sources = this.props.sources.map((pSource) =>
            this.makeSource(pSource),
        );
        this.navigator.clearActiveItem();

        const proms = [];
        for (const [index, pSource] of this.props.sources.entries()) {
            const source = this.state.sources[index];
            const options = this.loadOptions(pSource.options, request ?? "");
            if (options instanceof Promise) {
                source.isLoading = true;
                proms.push(
                    options.then(
                        (options) => {
                            if (!this._isSourceCurrent(source)) {
                                return;
                            }
                            source.options = options.map((option) =>
                                this.makeOption(option),
                            );
                            source.isLoading = false;
                        },
                        (error) => {
                            if (!this._isSourceCurrent(source)) {
                                return;
                            }
                            source.isLoading = false;
                            // A source that supersedes its own in-flight
                            // request (`many2x_autocomplete` does) reports the
                            // abandonment as a rejection. That is not a failure
                            // to show the user -- a newer request for the same
                            // source is already running.
                            if (error instanceof SupersededError) {
                                return;
                            }
                            this.reportSourceError(error);
                        },
                    ),
                );
            } else {
                source.options = options.map((option) => this.makeOption(option));
            }
        }

        try {
            await this.keepLast.add(Promise.all(proms));
        } catch (error) {
            if (error instanceof SupersededError) {
                // A newer load (or close()) owns the dropdown now.
                return;
            }
            throw error;
        }
        this._loadedRequest = request;
        this._loadedInputValue = inputValue;
        await this._enterLoadedOptions(entryDirection);
    }

    /**
     * Whether a source object still belongs to the load currently on screen:
     * a newer load replaces `state.sources` wholesale, detaching the previous
     * batch. Source ids are unique across loads, so identity is answered in
     * data space -- no reactivity proxy comparison.
     *
     * @param {{ id: number }} source
     * @returns {boolean}
     */
    _isSourceCurrent(source) {
        return this.sources.some((s) => s.id === source.id);
    }

    /**
     * The first option the user could land on, in display order, straight
     * from the loaded data. Deliberately not the navigator's first item: the
     * commit-on-blur decision is about what was *loaded*, and must hold even
     * when the parent closed the dropdown before the list ever rendered.
     * Sources still loading contribute nothing: they have no options yet.
     *
     * @returns {any | null}
     */
    _firstSelectableOption() {
        for (const source of this.sources) {
            if (source.isLoading) {
                continue;
            }
            const option = source.options.find((option) => !option.unselectable);
            if (option) {
                return option;
            }
        }
        return null;
    }

    /**
     * Presents a finished load: schedules the entry activation to run on the
     * navigator update that follows the render of the new list, so it lands
     * on the new DOM. Resolves once it has -- callers awaiting a load (enter,
     * tab) must observe the cursor it produces. When no update is coming --
     * the list will not render any navigable item and none is currently in
     * the DOM -- there is nothing to enter and it resolves immediately.
     *
     * @param {number} direction @see open
     * @returns {Promise<void>}
     */
    _enterLoadedOptions(direction) {
        const willRenderItems =
            this.displayOptions && Boolean(this._firstSelectableOption());
        if (!willRenderItems && !this.navigator.items.length) {
            this.navigator.clearActiveItem();
            return Promise.resolve();
        }
        this._entry?.applied.resolve();
        const applied = /** @type {Deferred<void>} */ (new Deferred());
        this._entry = { direction, applied };
        return applied;
    }

    onNavigationUpdated() {
        if (!this._entry) {
            return;
        }
        const { direction, applied } = this._entry;
        this._entry = null;
        if (direction < 0) {
            this.navigator.activateLast();
        } else {
            this.navigator.activateFirst();
        }
        applied.resolve();
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

    onInputBlur() {
        if (this.ignoreBlur) {
            this.ignoreBlur = false;
            return;
        }
        // Escape and Tab are the user saying "not this one". Leaving the field
        // afterwards must not resurrect the suggestion they just refused --
        // unlike a plain blur, which is what selectOnBlur is for.
        //
        // Neither must it commit suggestions that no longer answer what the box
        // holds: a parent replacing the value from outside writes over the box
        // and leaves the previous query's options behind, and committing the
        // first of those would overrule the parent's own write. Comparing the
        // two texts keeps that decision out of the render schedule -- both
        // sides are read off the input, not off when a re-render happened to
        // land.
        if (
            this.props.selectOnBlur &&
            !this.dismissed &&
            !this.isOptionSelected &&
            !this.loadingPromise &&
            this._loadedInputValue === this.inputRef.el.value.trim()
        ) {
            const option = this._firstSelectableOption();
            if (option) {
                this.selectOption(option);
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
                if (!this.isOpened || !this.activeOption) {
                    return;
                }
                this.selectOption(this.activeOption);
                break;
            case "escape":
                if (!this.isOpened) {
                    return;
                }
                this.dismissed = true;
                this.cancel();
                break;
            case "tab":
            case "shift+tab":
                if (!this.isOpened) {
                    return;
                }
                if (
                    this.props.autoSelect &&
                    this.activeOption &&
                    (this.navigationRev > 0 || this.inputRef.el.value.length)
                ) {
                    this.selectOption(this.activeOption);
                }
                this.dismissed = true;
                this.close();
                return;
            case "arrowup":
            case "arrowdown": {
                const direction = hotkey === "arrowdown" ? +1 : -1;
                this.navigationRev++;
                if (this.isOpened) {
                    if (direction > 0) {
                        this.navigator.next();
                    } else {
                        this.navigator.previous();
                    }
                } else {
                    // A closed list holds no option to step onto: the arrow has
                    // to enter it from the end it points away from, and that end
                    // is only known once the options exist. Stepping first would
                    // walk whatever the previous query left behind and then be
                    // overwritten by the load's own reset -- which is why both
                    // arrows used to land on the first option.
                    this.open(true, direction);
                }
                break;
            }
            default:
                return;
        }

        ev.stopPropagation();
        ev.preventDefault();
    }

    /**
     * The navigator drives hover for selectable options through its own armed
     * mouseenter/mouseleave listeners. Unselectable options are not navigable
     * items, but the pointer resting on one must still withdraw the highlight
     * -- a group header is "none of the choices" -- under the same arming
     * gate: a list rendered under a still cursor keeps its keyboard cursor.
     *
     * @param {[number, number]} indices
     */
    onOptionMouseEnter([sourceIndex, optionIndex]) {
        if (
            this.navigator.isMouseArmed &&
            this.sources[sourceIndex].options[optionIndex]?.unselectable
        ) {
            this.navigator.clearActiveItem();
        }
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
}
