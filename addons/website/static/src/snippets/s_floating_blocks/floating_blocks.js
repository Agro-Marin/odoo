/** @odoo-module native */
import { convertNumericToUnit, getHtmlStyle } from "@html_editor/utils/formatting";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.snippet.s_floating_blocks");

export class FloatingBlocks extends Interaction {
    static selector = ".s_floating_blocks";

    dynamicContent = {
        _window: {
            "t-on-resize": this.debounced(this.onResize, 100),
            "t-on-scroll": this.throttled(this.onScroll),
        },
        ".s_floating_blocks_block": {
            "t-att-style": (blockEl) => ({
                opacity: "1",
                top: this.boxesTops.get(blockEl),
                transform: this.boxesTransforms.get(blockEl),
            }),
            "t-on-keydown": this.onKeydown,
        },
    };

    setup() {
        this.boxScaleStep = 0.02;
        this.maximalScale = 0.98;
        this.minimalScale = this.maximalScale;

        this.boxesEls = this.el.querySelectorAll(".s_floating_blocks_block");

        this.initialGap = 16;
        this.stackingGap = this.initialGap * 0.8;

        this.boxesTops = new WeakMap();
        this.boxesTransforms = new WeakMap();
        this.boxesToAnimate = [];
        this.boxesScaleStep = [];
        this.boxesScaleProp = [];
    }

    start() {
        log.lifecycle("start", () => ({
            blocks: this.boxesEls.length,
            animated: this.boxesEls.length >= 2,
        }));
        this.adaptToHeaderChange();
        this.registerCleanup(
            this.services.website_menus.registerCallback(
                this.adaptToHeaderChange.bind(this),
            ),
        );

        if (this.boxesEls.length >= 2) {
            this.boxesToAnimate = Array.from(this.boxesEls).slice(0, -1);

            this.minimalScale = Math.max(
                this.maximalScale -
                    this.boxScaleStep * (this.boxesToAnimate.length - 1),
                0.7,
            );

            this.boxesScaleStep = this.calculateScaleFactors();
            log.pipeline("start: scale factors computed", () => ({
                boxesToAnimate: this.boxesToAnimate.length,
                minimalScale: this.minimalScale,
                steps: this.boxesScaleStep.length,
            }));

            this.onResize();
            this.onScroll();
            this.updateContent();
        }
    }

    /**
     * @returns {Array<number>}
     */
    calculateScaleFactors() {
        const boxesLength = this.boxesToAnimate.length;
        const boxesScaleStep = [];
        if (boxesLength === 0) {
            return boxesScaleStep;
        }

        if (boxesLength === 1) {
            boxesScaleStep.push(this.maximalScale);
            this.boxesScaleProp[0] = `scale3d(${this.maximalScale}, ${this.maximalScale}, ${this.maximalScale})`;

            return boxesScaleStep;
        }

        const scaleStep = (this.maximalScale - this.minimalScale) / (boxesLength - 1);

        for (let i = 0; i < boxesLength; i++) {
            const scale = this.minimalScale + scaleStep * i;
            boxesScaleStep.push(scale);

            this.boxesScaleProp[i] = `scale3d(${scale}, ${scale}, ${scale})`;
        }

        return boxesScaleStep;
    }

    adaptToHeaderChange() {
        let top = this.initialGap;
        for (const el of this.el.ownerDocument.querySelectorAll(
            ".o_top_fixed_element",
        )) {
            top += el.offsetHeight;
        }
        this.boxesEls.forEach((boxEl, index) => {
            this.boxesTops.set(boxEl, `${top + this.stackingGap * index}px`);
        });
    }

    updateZoom() {
        const scrollTop = window.scrollY;
        this.boxesToAnimate.forEach((blockEl, i) => {
            const blockGap = scrollTop - this.snippetOffset - this.snippetHeight * i;
            const transformValue = this.computeTransform(blockGap, i);
            this.boxesTransforms.set(blockEl, transformValue);
        });
    }

    /**
     * @param {number} blockGap
     * @param {number} index
     * @returns {string}
     */
    computeTransform(blockGap, index) {
        if (blockGap <= 0) {
            return "scale3d(1, 1, 1)";
        }

        const targetScale = this.boxesScaleStep[index];
        const scale = Math.max(targetScale, 1 - blockGap * this.snippetScaleFactor);

        if (Math.abs(scale - targetScale) < 0.001) {
            return this.boxesScaleProp[index];
        }

        return `scale3d(${scale}, ${scale}, ${scale})`;
    }

    onResize() {
        this.viewportHeight = window.innerHeight;
        this.snippetHeight = Math.min(
            this.boxesEls[0]?.offsetHeight || 0,
            window.innerHeight - 100,
        );
        this.snippetOffset = this.el.getBoundingClientRect().y + window.scrollY;
        this.snippetScaleFactor = 1 / (this.snippetHeight * 12);
        log.pipeline("onResize: geometry recomputed", () => ({
            viewportHeight: this.viewportHeight,
            snippetHeight: this.snippetHeight,
            snippetOffset: this.snippetOffset,
        }));

        this.updateZoom();
    }

    onScroll() {
        this.updateZoom();
    }
    /**
     * @param {KeyboardEvent} ev
     */
    onKeydown(ev) {
        const hotkey = getActiveHotkey(ev);
        if (hotkey === "shift+tab") {
            this.addListener(
                ev.currentTarget,
                "focusout",
                this.onShiftTabFocusout.bind(this),
                {
                    once: true,
                },
            );
        }
    }
    onShiftTabFocusout(ev) {
        if (
            !ev.relatedTarget ||
            ev.relatedTarget.closest(".s_floating_blocks_block") === ev.currentTarget
        ) {
            return;
        }
        const gap = convertNumericToUnit(3, "rem", "px", getHtmlStyle(document));
        log.logic(
            "onShiftTabFocusout: focus left block backwards, scrolling up",
            () => ({
                snippetHeight: this.snippetHeight,
                gap,
            }),
        );
        scrollTo(0, window.scrollY - (this.snippetHeight + gap));
    }
}

registry.category("public.interactions").add("website.floating_blocks", FloatingBlocks);
