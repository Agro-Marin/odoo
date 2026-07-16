// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/operation - Arithmetic operation class for numeric field transformations */

export class Operation {
    /**
     * @param {"+" | "-" | "*" | "/"} operator
     * @param {number} operand
     */
    constructor(operator, operand) {
        this.operator = operator;
        this.operand = operand;
    }

    /**
     * @param {number | string | boolean | null | undefined} value
     * @returns {number}
     */
    compute(value) {
        // Multi-edit operations ("+5", "-5", …) can be applied against a field
        // whose current value is ``false``/``undefined`` (never set) or a
        // non-numeric string. Coerce to a number first so the result stays
        // arithmetic instead of leaking ``NaN`` or a string concatenation into
        // ``_changes`` and the save payload.
        const current = Number(value) || 0;
        switch (this.operator) {
            case "+":
                return current + this.operand;
            case "-":
                return current - this.operand;
            case "*":
                return current * this.operand;
            case "/":
                return current / this.operand;
            default:
                throw new Error(`Unsupported operator: ${this.operator}`);
        }
    }
}
