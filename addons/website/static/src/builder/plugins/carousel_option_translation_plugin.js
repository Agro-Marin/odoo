/** @odoo-module native */
import { CarouselOptionPlugin } from "./carousel_option_plugin.js";

export class CarouselOptionTranslationPlugin extends CarouselOptionPlugin {
    static id = "carouselOption";
    static dependencies = ["builderOptions", "builderActions"];
}
