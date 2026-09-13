/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.interaction.image_shape_hover_effect");

export class ImageShapeHoverEffect extends Interaction {
    static selector = "img[data-hover-effect]";
    dynamicContent = {
        _root: {
            "t-on-mouseenter": this.mouseEnter,
            "t-on-mouseleave": this.mouseLeave,
        },
    };

    setup() {
        this.lastMouseEvent = Promise.resolve();
        this.originalImgSrc = this.el.getAttribute("src");
        this.svgInEl = null;
        this.svgOutEl = null;
        this.sourceObserver = new MutationObserver(() => {
            this.originalImgSrc = this.el.src;
        });
        this.connectSourceObserver();
        this.adjustImageSourceFrom = this.bindDeferred(this.adjustImageSourceFrom);
        log.lifecycle("ImageShapeHoverEffect setup: src observer attached", () => ({
            hoverEffect: this.el.dataset.hoverEffect,
            hasSrc: !!this.originalImgSrc,
        }));
    }

    destroy() {
        log.lifecycle(
            "ImageShapeHoverEffect destroy: restore src, observer disconnected",
            () => ({
                hoverEffect: this.el.dataset.hoverEffect,
            }),
        );
        this.el.src = this.originalImgSrc;
        this.disconnectSourceObserver();
    }
    connectSourceObserver() {
        this.sourceObserver.observe(this.el, {
            attributes: true,
            attributeFilter: ["src"],
        });
    }
    disconnectSourceObserver() {
        if (this.sourceObserver) {
            this.sourceObserver.disconnect();
        }
    }

    mouseEnter() {
        if (!this.originalImgSrc || !this.el.dataset.hoverEffect) {
            log.logic("ImageShapeHoverEffect mouseEnter: skip", () => ({
                hasSrc: !!this.originalImgSrc,
                hoverEffect: this.el.dataset.hoverEffect,
            }));
            return;
        }
        this.lastMouseEvent = this.lastMouseEvent.then(
            () =>
                new Promise((resolve) => {
                    if (!this.svgInEl) {
                        const endFetch = log.perf(
                            "ImageShapeHoverEffect mouseEnter: fetch svg",
                            () => ({
                                src: this.el.src,
                            }),
                        );
                        fetch(this.el.src)
                            .then((response) => response.text())
                            .then((text) => {
                                endFetch(() => ({ length: text.length }));
                                const parser = new DOMParser();
                                const result = parser.parseFromString(text, "text/xml");
                                const svg = result.getElementsByTagName("svg")[0];
                                this.svgInEl = svg;
                                if (!this.svgInEl) {
                                    log.logic(
                                        "ImageShapeHoverEffect mouseEnter: response has no svg",
                                        () => ({
                                            src: this.el.src,
                                        }),
                                    );
                                    resolve();
                                    return;
                                }
                                const animateEls = this.svgInEl.querySelectorAll(
                                    "#hoverEffects animateTransform, #hoverEffects animate",
                                );
                                animateEls.forEach((animateTransformEl) => {
                                    animateTransformEl.removeAttribute("begin");
                                });
                                this.setImgSrc(this.svgInEl, resolve);
                            })
                            .catch(() => {});
                    } else {
                        this.setImgSrc(this.svgInEl, resolve);
                    }
                }),
        );
    }

    mouseLeave() {
        this.lastMouseEvent = this.lastMouseEvent.then(
            () =>
                new Promise((resolve) => {
                    if (
                        !this.originalImgSrc ||
                        !this.svgInEl ||
                        !this.el.dataset.hoverEffect
                    ) {
                        resolve();
                        return;
                    }
                    if (!this.svgOutEl) {
                        this.svgOutEl = this.svgInEl.cloneNode(true);
                        const animateTransformEls = this.svgOutEl.querySelectorAll(
                            "#hoverEffects animateTransform, #hoverEffects animate",
                        );
                        animateTransformEls.forEach((animateTransformEl) => {
                            let valuesValue = animateTransformEl.getAttribute("values");
                            valuesValue = valuesValue.split(";").reverse().join(";");
                            animateTransformEl.setAttribute("values", valuesValue);
                        });
                    }
                    this.setImgSrc(this.svgOutEl, resolve);
                }),
        );
    }

    /**
     * @param {HTMLElement} svg
     * @param {Function} resolve
     */
    setImgSrc(svg, resolve) {
        if (this.isDestroyed) {
            log.logic("ImageShapeHoverEffect setImgSrc: destroyed, drop");
            return;
        }
        const previousRandomClass = [...svg.classList].find((cl) =>
            cl.startsWith("o_shape_anim_random_"),
        );
        svg.classList.remove(previousRandomClass);
        svg.classList.add("o_shape_anim_random_" + Date.now());
        const svgString = new XMLSerializer().serializeToString(svg);
        const preloadedImg = new Image();
        preloadedImg.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgString)}`;
        preloadedImg.onload = () => {
            if (this.isDestroyed) {
                resolve();
                return;
            }
            this.adjustImageSourceFrom(preloadedImg);
            this.hoveringImgSrc = preloadedImg.getAttribute("src");
            this.el.onload = () => {
                resolve();
            };
        };
    }

    /**
     * @param {HTMLImageElement} preloadedImageEl
     */
    adjustImageSourceFrom(preloadedImageEl) {
        if (this.isDestroyed) {
            return;
        }
        this.disconnectSourceObserver();
        this.el.src = preloadedImageEl.getAttribute("src");
        this.connectSourceObserver();
    }
}

registry
    .category("public.interactions")
    .add("website.image_shape_hover_effect", ImageShapeHoverEffect);
