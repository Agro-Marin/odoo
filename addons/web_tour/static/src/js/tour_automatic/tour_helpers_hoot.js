/** @odoo-module native */
import hoot from "@odoo/hoot-dom";
import { patch } from "@web/core/utils/patch";
import { TourHelpers } from "@web_tour/js/tour_automatic/tour_helpers";

patch(TourHelpers.prototype, {
    /**
     * @param {string|Node} selector
     * @example
     * @example
     */
    async check(selector) {
        const element = this._get_action_element(selector);
        await hoot.check(element);
    },

    /**
     * @param {Selector} selector
     * @example
     * @example
     */
    async clear(selector) {
        const element = this._get_action_element(selector);
        await hoot.click(element);
        await hoot.clear();
    },

    /**
     * @param {Selector} selector
     * @param {import("@odoo/hoot-dom").PointerOptions} options
     * @example
     * @example
     */
    async click(selector, options = { interactive: false }) {
        const element = this._get_action_element(selector);
        await hoot.click(element, options);
    },

    /**
     * @param {Selector} selector
     * @example
     * @example
     */
    async dblclick(selector) {
        const element = this._get_action_element(selector);
        await hoot.dblclick(element);
    },

    /**
     * @param {Selector} selector
     * @param {hoot.PointerOptions} options
     * @example
     * @example
     */
    async drag_and_drop(selector, options) {
        if (typeof options !== "object") {
            options = { position: "top", relative: true };
        }
        const dragEffectDelay = async () => {
            await hoot.animationFrame();
            await hoot.delay(this.delay);
        };

        const element = this.anchor;
        const { drop, moveTo } = await hoot.drag(element);
        await dragEffectDelay();
        await hoot.hover(element, {
            position: {
                top: 20,
                left: 20,
            },
            relative: true,
        });
        await dragEffectDelay();
        const target = await hoot.waitFor(selector, {
            visible: true,
            timeout: 1000,
        });
        await moveTo(target, options);
        await dragEffectDelay();
        await drop(target, options);
        await dragEffectDelay();
    },

    /**
     * @param {string} text
     * @param {Selector} selector
     * @example
     */
    async edit(text, selector) {
        const element = this._get_action_element(selector);
        await hoot.click(element);
        await hoot.edit(text);
    },

    /**
     * @param {string} text
     * @param {Selector} selector
     */
    async editor(text, selector) {
        const element = this._get_action_element(selector);
        const InEditor = Boolean(element.closest(".odoo-editor-editable"));
        if (!InEditor) {
            throw new Error("run 'editor' always on an element in an editor");
        }
        await hoot.click(element);
        this._set_range(element, "start");
        await hoot.keyDown("_");
        element.textContent = text;
        await hoot.manuallyDispatchProgrammaticEvent(element, "input");
        this._set_range(element, "stop");
        await hoot.keyUp("_");
        await hoot.manuallyDispatchProgrammaticEvent(element, "change");
    },

    /**
     * @param {string} value
     * @param {Selector} selector
     */
    async fill(value, selector) {
        const element = this._get_action_element(selector);
        await hoot.click(element);
        await hoot.fill(value);
    },

    /**
     * @param {Selector} selector
     * @param {import("@odoo/hoot-dom").PointerOptions} options
     * @example
     */
    async hover(selector, options) {
        const element = this._get_action_element(selector);
        await hoot.hover(element, options);
    },

    /**
     * @param {string|number} value
     * @param {Selector} selector
     */
    async range(value, selector) {
        const element = this._get_action_element(selector);
        await hoot.click(element);
        await hoot.setInputRange(element, value);
    },

    /** @example */
    async press(...args) {
        await hoot.press(
            args.flatMap((arg) => typeof arg === "string" && arg.split("+")),
        );
    },

    /**
     * @param {string} value
     * @param {Selector} selector
     * @example
     * @example
     */
    async select(value, selector) {
        const element = this._get_action_element(selector);
        await hoot.click(element);
        await hoot.select(value, { target: element });
    },

    /**
     * @param {number} index
     * @param {Selector} selector
     * @example
     */
    async selectByIndex(index, selector) {
        const element = this._get_action_element(selector);
        await hoot.click(element);
        const value = hoot.queryValue(`option:eq(${index})`, { root: element });
        if (value) {
            await hoot.select(value, { target: element });
            await hoot.manuallyDispatchProgrammaticEvent(element, "input");
        }
    },

    /**
     * @param {string|RegExp} contains
     * @param {Selector} selector
     * @example
     */
    async selectByLabel(contains, selector) {
        const element = this._get_action_element(selector);
        await hoot.click(element);
        const values = hoot.queryAllValues(`option:contains(${contains})`, {
            root: element,
        });
        await hoot.select(values, { target: element });
    },

    /**
     * @param {string|Node} selector
     * @example
     * @example
     */
    async uncheck(selector) {
        const element = this._get_action_element(selector);
        await hoot.uncheck(element);
    },

    /**
     * @param {string} url
     * @example
     */
    async goToUrl(url) {
        const linkEl = document.createElement("a");
        linkEl.href = url;
        await hoot.click(linkEl);
    },

    /** @param {string|Node} selector */
    async canvasNotEmpty(selector) {
        const canvas = this._get_action_element(selector);
        if (canvas.tagName.toLowerCase() !== "canvas") {
            throw new Error(`canvasNotEmpty is only suitable for canvas elements.`);
        }
        await hoot.waitUntil(() => {
            const context = canvas.getContext("2d");
            const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
            const pixels = new Uint32Array(imageData.data.buffer);
            return pixels.some((pixel) => pixel !== 0);
        });
    },

    /**
     * @param {Selector} selector
     * @returns {Node}
     */
    _get_action_element(selector) {
        if (typeof selector === "string" && selector.length) {
            const nodes = hoot.queryAll(selector);
            return nodes.find(hoot.isVisible) || nodes.at(0);
        } else if (typeof selector === "object" && Boolean(selector?.nodeType)) {
            return selector;
        }
        return this.anchor;
    },

    _set_range(element, start_or_stop) {
        function _node_length(node) {
            if (node.nodeType === Node.TEXT_NODE) {
                return node.nodeValue.length;
            } else {
                return node.childNodes.length;
            }
        }
        const selection = element.ownerDocument.getSelection();
        selection.removeAllRanges();
        const range = new Range();
        let node = element;
        let length = 0;
        if (start_or_stop === "start") {
            while (node.firstChild) {
                node = node.firstChild;
            }
        } else {
            while (node.lastChild) {
                node = node.lastChild;
            }
            length = _node_length(node);
        }
        range.setStart(node, length);
        range.setEnd(node, length);
        selection.addRange(range);
    },

    queryAll(target, options) {
        return hoot.queryAll(target, options);
    },

    queryFirst(target, options) {
        return hoot.queryFirst(target, options);
    },

    queryOne(target, options) {
        return hoot.queryOne(target, options);
    },

    waitFor(target, options) {
        return hoot.waitFor(target, options);
    },

    waitUntil(predicate, options) {
        return hoot.waitUntil(predicate, options);
    },

    animationFrame(...args) {
        return hoot.animationFrame(...args);
    },
});
