/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import {
    adaptHighlightPosition,
    closestToObserve,
    getCurrentTextHighlight,
    getObservedEls,
    makeHighlightSvgs,
} from "@website/js/highlight_utils";

const log = makeLogger("website.interaction.text_highlights");

export class TextHighlight extends Interaction {
    static selector = "#wrapwrap, .o_wslides_fs_content";
    dynamicContent = {
        _root: {
            "t-on-text_highlight_added": ({ target }) =>
                this.onTextHighlightAdded(target),
        },
    };

    setup() {
        this.resizeObserver = new window.ResizeObserver(this.updateEntries.bind(this));
        this.mutationObserver = new window.MutationObserver(
            this.updateEntries.bind(this),
        );
        log.lifecycle("TextHighlight setup: observers created", () => ({
            root: this.el.id || this.el.className,
        }));
    }

    start() {
        log.pipeline("TextHighlight start: observe highlights", () => ({
            highlights: this.el.querySelectorAll(".o_text_highlight").length,
        }));
        for (const textEl of this.el.querySelectorAll(".o_text_highlight")) {
            this.handleEl(textEl);
        }
    }

    destroy() {
        log.lifecycle(
            "TextHighlight destroy: observers disconnected, svgs removed",
            () => ({
                svgs: this.el.querySelectorAll(".o_text_highlight_svg").length,
            }),
        );
        this.resizeObserver.disconnect();
        this.mutationObserver.disconnect();
        for (const svg of this.el.querySelectorAll(".o_text_highlight_svg")) {
            svg.remove();
        }
    }

    updateEntries(entries) {
        this.waitForAnimationFrame(() => this._updateEntries(entries));
    }
    _updateEntries(entries) {
        const endUpdate = log.perf("TextHighlight rebuild highlight svgs");
        const closestToObserves = new Set();
        for (const { target, addedNodes = [], removedNodes = [] } of entries) {
            const elements = [target, ...addedNodes, ...removedNodes]
                .map((el) =>
                    el.nodeType === Node.ELEMENT_NODE ? el : el.parentElement,
                )
                .filter(Boolean);
            if (!elements.length) {
                continue;
            }
            const hasSvg = elements.some((el) => el.closest(".o_text_highlight_svg"));
            if (hasSvg) {
                continue;
            }
            closestToObserves.add(this.closestToObserve(target));
        }
        for (const closestToObserve of closestToObserves) {
            for (const el of closestToObserve.querySelectorAll(".o_text_highlight")) {
                const highlightID = getCurrentTextHighlight(el);
                const currentSVGs = el.querySelectorAll(".o_text_highlight_svg");
                for (const svg of currentSVGs) {
                    svg.remove();
                }
                const svgs = makeHighlightSvgs(el, highlightID);
                for (const svg of svgs) {
                    this.insert(svg, el, "beforeend", false);
                    adaptHighlightPosition(el, svg);
                }
            }
        }
        endUpdate(() => ({
            entries: entries.length,
            containers: closestToObserves.size,
        }));
    }
    /**
     * @param {HTMLElement} el
     */
    closestToObserve(el) {
        return closestToObserve(el, this.el);
    }

    /**
     * @param {HTMLElement} el
     */
    getObservedEls(el) {
        return getObservedEls(el);
    }

    /**
     * @param {HTMLElement} el
     */
    handleEl(el) {
        for (const elToObserve of this.getObservedEls(el)) {
            this.resizeObserver.observe(elToObserve);
        }
        const closestToObserve = this.closestToObserve(el);
        this.mutationObserver.observe(closestToObserve, {
            childList: true,
            characterData: true,
            subtree: true,
        });
        this.mutationObserver.observe(el, {
            attributes: true,
        });
        this.updateEntries([{ target: el }]);
    }

    /**
     * @param {HTMLElement} el
     */
    onTextHighlightAdded(el) {
        log.logic("TextHighlight onTextHighlightAdded", () => ({
            highlight: getCurrentTextHighlight(el),
        }));
        this.handleEl(el);
    }
}

registry.category("public.interactions").add("website.text_highlight", TextHighlight);

registry.category("public.interactions.edit").add("website.text_highlight", {
    Interaction: TextHighlight,
});
