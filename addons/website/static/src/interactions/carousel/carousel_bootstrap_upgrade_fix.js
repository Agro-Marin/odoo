/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Carousel } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.interaction.carousel_bootstrap_upgrade_fix");

export class CarouselBootstrapUpgradeFix extends Interaction {
    static selector = [
        "[data-snippet='s_image_gallery'] .carousel",
        "[data-snippet='s_carousel'] .carousel",
        "[data-snippet='s_quotes_carousel'] .carousel",
        "[data-snippet='s_quotes_carousel_minimal'] .carousel",
        "[data-snippet='s_carousel_intro'] .carousel",
        "#o-carousel-product.carousel",
    ].join(", ");
    dynamicContent = {
        _root: {
            "t-on-slide.bs.carousel": () => (this.sliding = true),
            "t-on-slid.bs.carousel": () => (this.sliding = false),
            "t-att-class": () => ({
                o_carousel_sliding: this.sliding,
            }),
        },
    };
    carouselOptions = undefined;

    setup() {
        this.sliding = false;
        this.hasInterval = ![undefined, "false", "0"].includes(
            this.el.dataset.bsInterval,
        );
    }

    async willStart() {
        if (this.hasInterval || this.el.dataset.bsRide) {
            if (this.el.classList.contains("o_carousel_sliding")) {
                const endWaitSlid = log.perf(
                    "CarouselBootstrapUpgradeFix willStart: wait slid",
                    () => ({
                        id: this.el.id,
                    }),
                );
                await new Promise((resolve) => {
                    this.addListener(this.el, "slid.bs.carousel", () => resolve(), {
                        once: true,
                    });
                });
                endWaitSlid();
            }
            log.logic(
                "CarouselBootstrapUpgradeFix willStart: dispose previous instance",
                () => ({
                    id: this.el.id,
                    hasInterval: this.hasInterval,
                    ride: this.el.dataset.bsRide,
                }),
            );
            Carousel.getInstance(this.el)?.dispose();
        }
    }

    start() {
        if (this.hasInterval || this.el.dataset.bsRide) {
            const carousel = Carousel.getOrCreateInstance(
                this.el,
                this.carouselOptions,
            );
            log.lifecycle(
                "CarouselBootstrapUpgradeFix start: carousel created",
                () => ({
                    id: this.el.id,
                    carouselOptions: this.carouselOptions,
                }),
            );
            this.registerCleanup(() => carousel.dispose());
        }
    }
}

registry
    .category("public.interactions")
    .add("website.carousel_bootstrap_upgrade_fix", CarouselBootstrapUpgradeFix);
