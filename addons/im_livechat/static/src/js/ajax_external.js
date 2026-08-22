/** @odoo-module native */
import { assets } from "@web/core/assets";

assets.loadJS = function (url) {
    console.warn("Tried to load the following script on an external website: " + url);
};
