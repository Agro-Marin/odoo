/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { ImageShapeHoverEffect } from "@website/interactions/image_shape_hover_effect";

const log = makeLogger("website.interaction.image_shape_hover_effect.edit");

const ImageShapeHoverEffectEdit = (I) =>
    class extends I {
        destroy() {
            log.lifecycle("ImageShapeHoverEffectEdit destroy", () => ({
                restoreOriginal: this.el.src === this.hoveringImgSrc,
            }));
            if (this.el.src === this.hoveringImgSrc) {
                this.el.src = this.originalImgSrc;
            }
            this.disconnectSourceObserver();
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
                                let valuesValue =
                                    animateTransformEl.getAttribute("values");
                                valuesValue = valuesValue
                                    .split(";")
                                    .reverse()
                                    .join(";");
                                animateTransformEl.setAttribute("values", valuesValue);
                            });
                        }
                        this.setImgSrc(this.svgOutEl, () => {
                            setTimeout(() => {
                                if (this.isDestroyed) {
                                    resolve();
                                    return;
                                }
                                this.disconnectSourceObserver();
                                this.el.src = this.originalImgSrc;
                                this.connectSourceObserver();
                                this.el.onload = () => {
                                    resolve();
                                };
                            }, this.getAnimationMaxDuration(this.svgOutEl));
                        });
                    }),
            );
        }

        getAnimationMaxDuration(svg) {
            let maxDuration = 0;
            const animateEls = svg.querySelectorAll(
                "#hoverEffects animateTransform, #hoverEffects animate",
            );
            animateEls.forEach((animateEl) => {
                const dur = animateEl.getAttribute("dur");
                if (dur) {
                    const duration = parseFloat(dur) * (dur.endsWith("ms") ? 1 : 1000);
                    maxDuration = Math.max(maxDuration, duration);
                }
            });
            return maxDuration;
        }
    };

registry.category("public.interactions.edit").add("website.image_shape_hover_effect", {
    Interaction: ImageShapeHoverEffect,
    mixin: ImageShapeHoverEffectEdit,
});
