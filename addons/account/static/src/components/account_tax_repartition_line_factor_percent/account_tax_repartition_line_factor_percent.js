/** @odoo-module native */
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { roundPrecision } from "@web/core/utils/format/numbers";
import { FloatField, floatField } from "@web/fields/basic/float/float_field";

const MIN_DECIMALS = 2;

export class AccountTaxRepartitionLineFactorPercent extends FloatField {
    static defaultProps = {
        ...FloatField.defaultProps,
        digits: [16, 12],
    };

    /**
     * @override
     */
    get formattedValue() {
        const value = super.formattedValue;
        const { decimalPoint } = localization;
        const separatorIndex = value.lastIndexOf(decimalPoint);
        if (separatorIndex === -1) {
            return value;
        }
        const integerPart = value.slice(0, separatorIndex);
        const decimals = value
            .slice(separatorIndex + decimalPoint.length)
            .replace(/0+$/, "")
            .padEnd(MIN_DECIMALS, "0");
        return `${integerPart}${decimalPoint}${decimals}`;
    }

    /**
     * @override
     */
    parse(value) {
        const parsedValue = super.parse(value);
        if (!Number.isFinite(parsedValue)) {
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
