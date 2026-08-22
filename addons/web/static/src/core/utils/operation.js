// @ts-check
/** @odoo-module native */

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
