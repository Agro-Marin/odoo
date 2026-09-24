/** @odoo-module native */
import { useBuilderContext } from "@html_builder/core/builder_context";
import { useOperation } from "@html_builder/core/operation_plugin";
import { useDomState } from "@html_builder/core/utils";
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.carousel_item_header_buttons");

export class CarouselItemHeaderMiddleButtons extends Component {
    static template = "website.CarouselItemHeaderMiddleButtons";
    static props = {
        applyAction: Function,
        addSlide: Function,
        removeSlide: Function,
    };

    setup() {
        this.builderContext = useBuilderContext();
        useLifecycleLog(log);
        this.callOperation = useOperation();
        this.state = useDomState((editingElement) => {
            const carouselItemsNumber = editingElement.parentElement.children.length;
            return {
                hasMultiItems: carouselItemsNumber > 1,
            };
        });
    }

    slide(direction) {
        const applySpec = {
            editingElement: this.builderContext
                .getEditingElement()
                .closest(".carousel"),
            params: {
                direction: direction,
            },
        };

        log.pipeline("slide", { direction });
        this.props.applyAction("slideCarousel", applySpec);
    }

    addSlide() {
        const carouselEl = this.builderContext.getEditingElement().closest(".carousel");

        this.callOperation(async () => {
            const endAddSlide = log.perf("addSlide");
            await this.props.addSlide(carouselEl);
            endAddSlide(() => ({
                slides: carouselEl?.querySelectorAll(".carousel-item").length,
            }));
        });
    }

    removeSlide() {
        this.callOperation(async () => {
            const endRemoveSlide = log.perf("removeSlide");
            await this.props.removeSlide(this.builderContext.getEditingElement());
            endRemoveSlide();
        });
    }
}
