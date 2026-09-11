/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class ZoomedBackgroundShape extends Interaction {
    static selector = ".o_we_shape";
    dynamicContent = {
        _window: {
            "t-on-resize": this.throttled(this.resizeBackgroundShape),
        },
        _root: {
            "t-att-style": () => ({
                left: this.offset,
                right: this.offset,
            }),
        },
    };

    setup() {
        this.offset = undefined;
    }

    start() {
        this.resizeBackgroundShape();
        this.updateContent();
    }

    resizeBackgroundShape() {
        this.offset = undefined;
        this.updateContent();
        let decimalPart = this.el.getBoundingClientRect().width % 1;
        decimalPart = parseFloat(decimalPart.toFixed(2));
        decimalPart = decimalPart === 1 ? 0 : decimalPart;
        if (decimalPart > 0) {
            this.offset = `${(decimalPart < 0.5 ? decimalPart : decimalPart - 1) / 2}px`;
        }
    }
}

registry
    .category("public.interactions")
    .add("website.zoomed_background_shape", ZoomedBackgroundShape);
