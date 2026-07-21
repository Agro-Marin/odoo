/** @odoo-module native */
import { registry } from "@web/core/registry";
import { roundPrecision } from "@web/core/utils/format/numbers";
import { FloatField, floatField } from "@web/fields/basic/float/float_field";

export class AccountTaxRepartitionLineFactorPercent extends FloatField {
    static defaultProps = {
        ...FloatField.defaultProps,
        digits: [16, 12],
    };

    /**
     * @override
     * Strip trailing zeros so values are not displayed with all 12 digits.
     */
    get formattedValue() {
        const value = super.formattedValue;
        const trailingNumbersMatch = value.match(/(\d+)$/);
        if (!trailingNumbersMatch) {
            return value;
        }
        const trailingZeroMatch = trailingNumbersMatch[1].match(/(0+)$/);
        if (!trailingZeroMatch) {
            return value;
        }
        const nbTrailingZeroToRemove = Math.min(
            trailingZeroMatch[1].length,
            trailingNumbersMatch[1].length - 2,
        );
        return value.substring(0, value.length - nbTrailingZeroToRemove);
    }

    /**
     * @override
     * Round to the field precision so an expression like "= 2/3" saves the
     * rounded value shown on screen, not the unrounded result.
     */
    parse(value) {
        const parsedValue = super.parse(value);
        try {
            Number(parsedValue);
        } catch {
            return parsedValue;
        }
        const precisionRounding = Number(`1e-${this.props.digits[1]}`);
        return roundPrecision(parsedValue, precisionRounding);
    }
}

export const accountTaxRepartitionLineFactorPercent = {
    ...floatField,
    component: AccountTaxRepartitionLineFactorPercent,
};

registry
    .category("fields")
    .add(
        "account_tax_repartition_line_factor_percent",
        accountTaxRepartitionLineFactorPercent,
    );
