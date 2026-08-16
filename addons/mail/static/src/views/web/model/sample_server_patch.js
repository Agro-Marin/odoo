/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { SampleServer } from "@web/model/sample_server";
patch(SampleServer.prototype, {
    /**
     * @param {string} modelName
     * @param {{name: string}} field
     * @returns {*}
     */
    _getRandomSelectionValue(modelName, field) {
        if (field.name === "activity_exception_decoration") {
            return false;
        }
        return super._getRandomSelectionValue(...arguments);
    },
});
