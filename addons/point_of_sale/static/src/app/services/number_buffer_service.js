/** @odoo-module native */
import { barcodeService } from "@barcodes/barcode_service";
import { EventBus, onWillDestroy, useComponent } from "@odoo/owl";
import { parseFloat as oParseFloat } from "@web/core/parsers";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

const INPUT_KEYS = new Set(
    ["Delete", "Backspace", "+1", "+2", "+5", "+10", "+20", "+50"].concat(
        "0123456789+-.,".split(""),
    ),
);
const CONTROL_KEYS = new Set(["Enter", "Esc"]);
const ALLOWED_KEYS = new Set([...INPUT_KEYS, ...CONTROL_KEYS]);
const getDefaultConfig = () => ({
    decimalPoint: false,
    triggerAtEnter: false,
    triggerAtEsc: false,
    triggerAtInput: false,
    useWithBarcode: false,
});

class NumberBuffer extends EventBus {
    static serviceDependencies = ["mail.sound_effects", "localization", "overlay"];
    constructor() {
        super();
        this.setup(...arguments);
    }
    setup(services) {
        this.state = {};
        this.isReset = false;
        this.bufferHolderStack = [];
        this.sound = services["mail.sound_effects"];
        this.localization = services.localization;
        this.overlay = services.overlay;
        window.addEventListener("keyup", this._onKeyboardInput.bind(this));
    }
    /**
     * @returns {String}
     */
    get() {
        return this.state ? this.state.buffer : null;
    }
    /**
     * @param {String} val
     */
    set(val) {
        this.state.lastSet = val;
        this.state.buffer = !isNaN(parseFloat(val)) ? val : "";
        this.trigger("buffer-update", this.state.buffer);
    }
    reset() {
        this.isReset = true;
        this.state.buffer = "";
        this.trigger("buffer-update", this.state.buffer);
    }
    capture() {
        if (this.handler) {
            clearTimeout(this._timeout);
            this.handler(true);
            delete this.handler;
        }
    }
    /**
     * @returns {number}
     */
    getFloat() {
        return oParseFloat(this.get());
    }
    /**
     * @param {Object} config
     * @param {String|null} config.decimalPoint
     * @param {String|null} config.triggerAtEnter
     * @param {String|null} config.triggerAtEsc
     * @param {String|null} config.triggerAtInput
     * @param {Boolean} config.useWithBarcode
     */
    use(config) {
        this.eventsBuffer = [];
        const currentComponent = useComponent();
        config = Object.assign(getDefaultConfig(), config);

        const holder = {
            component: currentComponent,
            state: config.state ? config.state : { buffer: "", toStartOver: false },
            config,
        };
        this.bufferHolderStack.push(holder);
        this._setUp();
        onWillDestroy(() => {
            const indexComponent = this.bufferHolderStack.indexOf(holder);
            if (indexComponent !== -1) {
                this.bufferHolderStack.splice(indexComponent, 1);
            }
            this._setUp();
        });
    }
    get _currentBufferHolder() {
        return this.bufferHolderStack[this.bufferHolderStack.length - 1];
    }
    _setUp() {
        if (!this._currentBufferHolder) {
            return;
        }
        const { component, state, config } = this._currentBufferHolder;
        this.component = component;
        this.state = state;
        this.config = config;
        this.decimalPoint = config.decimalPoint || this.localization.decimalPoint;
        this.maxTimeBetweenKeys = this.config.useWithBarcode
            ? barcodeService.maxTimeBetweenKeysInMs
            : 0;
    }
    _onKeyboardInput(event) {
        const overlays = Object.values(this.overlay.overlays);
        if (overlays.length && !this._currentBufferHolder?.config?.captureWithOverlay) {
            return;
        }
        return (
            this._currentBufferHolder &&
            this._bufferEvents(this._onInput((event) => event.key))(event)
        );
    }
    sendKey(key) {
        const event = new CustomEvent("", {
            detail: {
                key: key,
            },
        });
        Object.defineProperty(event, "target", { value: {} });

        return this._bufferEvents(this._onInput((event) => event.detail.key))(event);
    }
    _bufferEvents(handler) {
        return (event) => {
            if (
                ["INPUT", "TEXTAREA"].includes(event.target.tagName) ||
                !this.eventsBuffer
            ) {
                return;
            }
            if (event.ctrlKey || event.metaKey || event.altKey) {
                return;
            }
            clearTimeout(this._timeout);
            this.eventsBuffer.push(event);
            this._timeout = setTimeout(handler, this.maxTimeBetweenKeys);
            this.handler = handler;
        };
    }
    _onInput(keyAccessor) {
        return (manualCapture = false) => {
            if (
                manualCapture ||
                session.test_mode ||
                (!manualCapture && this.eventsBuffer.length <= 2)
            ) {
                for (const event of this.eventsBuffer) {
                    if (!ALLOWED_KEYS.has(keyAccessor(event))) {
                        this.eventsBuffer = [];
                        return;
                    }
                }
                for (const event of this.eventsBuffer) {
                    this._handleInput(keyAccessor(event));
                    event.preventDefault();
                    event.stopPropagation();
                }
            }
            this.eventsBuffer = [];
        };
    }
    _handleInput(key) {
        if (key === "Enter" && this.config.triggerAtEnter) {
            this.config.triggerAtEnter(this.state);
        } else if (key === "Esc" && this.config.triggerAtEsc) {
            this.config.triggerAtEsc(this.state);
        } else if (INPUT_KEYS.has(key)) {
            this._updateBuffer(key);
            if (this.config.triggerAtInput) {
                this.config.triggerAtInput({
                    buffer: this.state.buffer,
                    key,
                });
            }
        }
    }
    /**
     * @param {String} input
     */
    _updateBuffer(input) {
        const isEmpty = (val) => val === "" || val === null;
        if (input === undefined || input === null) {
            return;
        }
        const isFirstInput = isEmpty(this.state.buffer);
        if (input === "," || input === ".") {
            if (this.state.toStartOver) {
                this.state.buffer = "";
            }
            if (isFirstInput) {
                this.state.buffer = "0" + this.decimalPoint;
            } else if (!this.state.buffer.length || this.state.buffer === "-") {
                this.state.buffer += "0" + this.decimalPoint;
            } else if (this.state.buffer.indexOf(this.decimalPoint) < 0) {
                this.state.buffer = this.state.buffer + this.decimalPoint;
            }
        } else if (input === "Delete") {
            if (this.isReset) {
                this.state.buffer = "";
                this.isReset = false;
                return;
            }
            this.state.buffer = isEmpty(this.state.buffer) ? null : "";
        } else if (input === "Backspace") {
            if (this.isReset) {
                this.state.buffer = "";
                this.isReset = false;
                return;
            }
            if (this.state.toStartOver) {
                this.state.buffer = "";
            }
            const buffer = this.state.buffer;
            if (isEmpty(buffer)) {
                this.state.buffer = null;
            } else {
                this.state.buffer = buffer.substring(0, buffer.length - 1);
            }
        } else if (input === "+") {
            if (this.state.buffer[0] === "-") {
                this.state.buffer = this.state.buffer.substring(
                    1,
                    this.state.buffer.length,
                );
            }
        } else if (input === "-") {
            if (isFirstInput) {
                this.state.buffer = "-0";
            } else if (this.state.buffer[0] === "-") {
                this.state.buffer = this.state.buffer.substring(
                    1,
                    this.state.buffer.length,
                );
            } else {
                this.state.buffer = "-" + this.state.buffer;
            }
        } else if (input[0] === "+" && !isNaN(parseFloat(input))) {
            const inputValue = oParseFloat(input.slice(1));
            const currentBufferValue = this.state.buffer
                ? oParseFloat(this.state.buffer.replace(".", this.decimalPoint))
                : 0;
            this.state.buffer = (inputValue + currentBufferValue)
                .toString()
                .replace(".", this.decimalPoint);
        } else if (!isNaN(parseInt(input, 10))) {
            if (this.state.toStartOver) {
                this.state.buffer = "";
            }
            if (this.state.buffer === this.state.lastSet) {
                this.state.buffer = "";
                this.state.lastSet = false;
            }
            if (isFirstInput) {
                this.state.buffer = "" + input;
            } else if (this.state.buffer.length > 12) {
                this.sound.play("bell");
            } else {
                this.state.buffer += input;
            }
        }
        if (this.state.buffer === "-") {
            this.state.buffer = "";
        }
        this.isReset = false;
        this.state.toStartOver = false;

        this.trigger("buffer-update", this.state.buffer);
    }
}

export const numberBufferService = {
    dependencies: NumberBuffer.serviceDependencies,
    start(env, deps) {
        return new NumberBuffer(deps);
    },
};

registry.category("services").add("number_buffer", numberBufferService);
