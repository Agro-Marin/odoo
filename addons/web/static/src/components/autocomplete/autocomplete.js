// @ts-check
/** @odoo-module native */

/** @module @web/components/autocomplete/autocomplete - Generic autocomplete dropdown with multi-source results, keyboard navigation, and debounced search */

import {
    Component,
    onMounted,
    onWillDestroy,
    onWillUpdateProps,
    useRef,
    useState,
} from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { usePosition } from "@web/core/position/position_hook";
import { Deferred } from "@web/core/utils/concurrency";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { isScrollableY, scrollTo } from "@web/core/utils/dom/scrolling";
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
        this.nextSourceId = 0;
        this.nextOptionId = 0;
        this.sources = [];
        this.inEdition = false;
        this.mouseSelectionActive = false;
        this.isOptionSelected = false;

        this.state = useState({
            navigationRev: 0,
            optionsRev: 0,
            open: false,
            activeSourceOption: null,
            value: this.props.value,
        });

        this.inputRef = /** @type {any} */ (useForwardRefToParent("input"));
        this.listRef = useRef("sourcesList");
        if (this.props.autofocus) {
            useAutofocus({ refName: "input" });
        }
        this.root = useRef("root");

        this.debouncedProcessInput = useDebounced(async () => {
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
        }, this.timeout);

        // Listeners are registered only while the dropdown is open, to avoid
        // firing on every mouse move / scroll while closed. Arrow functions
        // capture `this` since addEventListener won't do it for us.
        this._externalClose = (/** @type {Event} */ ev) => this.externalClose(ev);
        // One-shot latch: the first mousemove flips mouseSelectionActive and
        // removes itself; re-armed on close/keyboard nav so hover keeps working.
        this._onMouseMove = () => {
            this._mouseMoveCleanup = null;
            this.mouseSelectionActive = true;
        };
        this._globalCleanups = [];
        this._mouseMoveCleanup = null;
        // onWillDestroy (not onWillUnmount): a component destroyed before
        // "mounted" never runs willUnmount, which would leak the capture-phase
        // window listeners and let them fire against a null root ref.
        onWillDestroy(() => this._removeGlobalListeners());

        onWillUpdateProps((nextProps) => {
            if (this.props.value !== nextProps.value || this.forceValFromProp) {
                this.forceValFromProp = false;
                if (!this.inEdition) {
                    this.state.value = nextProps.value;
                    this.inputRef.el.value = nextProps.value;
                }
                // A prop value change means the owner replaced the value out from
                // under us; close so the next interaction re-opens a fresh dropdown
                // instead of a stale one that would toggle shut on click.
                this.close();
            }
        });

        // position and size
        if (this.props.dropdown) {
            usePosition("sourcesList", () => this.targetDropdown, this.dropdownOptions);
        } else {
            // Open eagerly so sources start loading on first render (quick-add
            // flows type immediately). Window listeners are deferred to mount
            // though, since a pre-mount destroy would leak them permanently.
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

    get activeSourceOptionId() {
        if (!this.isOpened || !this.state.activeSourceOption) {
            return undefined;
        }
        const [sourceIndex, optionIndex] = this.state.activeSourceOption;
        const source = this.sources[sourceIndex];
        return `${this.props.id || "autocomplete"}_${sourceIndex}_${
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
        this._resetMouseSelection();
        this._removeGlobalListeners();
    }

    _addGlobalListeners() {
        if (this._globalCleanups.length) {
            return; // already registered
        }
        const add = (target, event, handler, capture = false) => {
            target.addEventListener(event, handler, capture);
            this._globalCleanups.push(() =>
                target.removeEventListener(event, handler, capture),
            );
        };
        add(window, "scroll", this._externalClose, true);
        add(window, "pointerdown", this._externalClose);
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

    /** Arm the one-shot mousemove latch: first move sets mouseSelectionActive then self-removes. */
    _armMouseMove() {
        if (this._mouseMoveCleanup) {
            return; // already armed
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

    /** Turn off mouse hover selection and re-arm the mousemove latch. */
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
        this.close();
    }

    async loadSources(useInput) {
        // Order guard for overlapping loads (fast typing over a slow async
        // source): only the most recent invocation may mutate state, so a
        // stale resolution can't bump optionsRev or run navigate()/scroll()
        // out of order. SearchBar wraps calls in KeepLast; other consumers
        // (record selectors, many2one widgets) rely on this guard directly.
        const loadId = (this._loadId = (this._loadId ?? 0) + 1);
        this.sources = [];
        this.state.activeSourceOption = null;
        const proms = [];
        for (const pSource of this.props.sources) {
            const source = this.makeSource(pSource);
            this.sources.push(source);

            const options = this.loadOptions(
                pSource.options,
                useInput ? this.inputRef.el.value.trim() : "",
            );
            if (options instanceof Promise) {
                source.isLoading = true;
                const prom = options.then((options) => {
                    if (loadId !== this._loadId) {
                        return; // superseded by a newer load
                    }
                    source.options = options.map((option) => this.makeOption(option));
                    source.isLoading = false;
                    this.state.optionsRev++;
                });
                proms.push(prom);
            } else {
                source.options = options.map((option) => this.makeOption(option));
            }
        }

        await Promise.all(proms);
        if (loadId !== this._loadId) {
            return; // a newer load is in flight; let it finalize navigation
        }
        this.navigate(0);
        this.scroll();
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

    navigate(direction) {
        // Navigation takes over from the mouse: disarm hover selection and
        // re-arm the latch so the next real mousemove re-enables it.
        this._resetMouseSelection();
        let step = Math.sign(direction);
        if (!step) {
            this.state.activeSourceOption = null;
            step = 1;
        } else {
            this.state.navigationRev++;
        }

        let maxIterations = this.sources.reduce((n, s) => n + s.options.length, 0) + 1;
        do {
            if (this.state.activeSourceOption) {
                let [sourceIndex, optionIndex] = this.state.activeSourceOption;
                let source = this.sources[sourceIndex];

                optionIndex += step;
                if (0 > optionIndex || optionIndex >= source.options.length) {
                    sourceIndex += step;
                    source = this.sources[sourceIndex];

                    // Skip loaded-but-empty sources too (same predicate as the
                    // initial-selection branch below): landing on one would set
                    // activeSourceOption on a nonexistent option, crashing
                    // Enter/Tab and emitting a dangling aria-activedescendant.
                    while (source && (source.isLoading || !source.options.length)) {
                        sourceIndex += step;
                        source = this.sources[sourceIndex];
                    }

                    if (source) {
                        optionIndex = step < 0 ? source.options.length - 1 : 0;
                    }
                }

                this.state.activeSourceOption = source
                    ? [sourceIndex, optionIndex]
                    : null;
            } else {
                let sourceIndex = step < 0 ? this.sources.length - 1 : 0;
                let source = this.sources[sourceIndex];

                while (source && (source.isLoading || !source.options.length)) {
                    sourceIndex += step;
                    source = this.sources[sourceIndex];
                }

                if (source) {
                    const optionIndex = step < 0 ? source.options.length - 1 : 0;
                    if (optionIndex < source.options.length) {
                        this.state.activeSourceOption = [sourceIndex, optionIndex];
                    }
                }
            }
        } while (this.activeOption?.unselectable && --maxIterations > 0);
    }

    onInputBlur() {
        if (this.ignoreBlur) {
            this.ignoreBlur = false;
            return;
        }
        // selectOnBlur: auto-select the first suggestion, if any, on blur.
        // Skip while a load is in flight: the displayed options belong to a
        // previous search string and would auto-select a stale option.
        if (
            this.props.selectOnBlur &&
            !this.isOptionSelected &&
            !this.loadingPromise &&
            this.sources[0]
        ) {
            const firstOption = this.sources[0].options[0];
            if (firstOption) {
                this.state.activeSourceOption = firstOption.unselectable
                    ? null
                    : [0, 0];
                if (this.activeOption) {
                    this.selectOption(this.activeOption);
                }
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
            // Nothing necessarily awaits this promise: swallow the rejection
            // to avoid an unhandled rejection when a source fails to load.
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
            } catch {
                // Sources failed to load: proceed as if there were no options.
            }
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
        // Mirror onOptionMouseEnter's gate: only clear an activation the mouse
        // set, else a stray mouseleave after keyboard nav could wipe it out.
        if (!this.mouseSelectionActive) {
            return;
        }
        this.state.activeSourceOption = null;
    }
    onOptionClick(option) {
        this.selectOption(option);
        this.inputRef.el.focus();
    }
    onOptionPointerDown(option, ev) {
        this.ignoreBlur = true;
        if (option.unselectable) {
            ev.preventDefault();
        }
    }

    externalClose(/** @type {Event} */ ev) {
        if (this.isOpened && !this.root.el.contains(/** @type {Node} */ (ev.target))) {
            this.cancel();
        }
    }

    scroll() {
        if (!this.activeSourceOptionId) {
            return;
        }
        if (isScrollableY(this.listRef.el)) {
            // props.id is embedded verbatim in the option ids: escape it so
            // CSS-significant characters can't break the selector.
            const element = this.listRef.el.querySelector(
                `#${CSS.escape(this.activeSourceOptionId)}`,
            );
            if (element) {
                scrollTo(element);
            }
        }
    }
}
