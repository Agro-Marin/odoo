import { mailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels, onRpc } from "@web/../tests/web_test_helpers";

import { AccountCashRounding } from "./account_cash_rounding.data.js";
import { AccountFiscalPosition } from "./account_fiscal_position.data.js";
import { AccountJournal } from "./account_journal.data.js";
import { AccountMove } from "./account_move.data.js";
import { AccountTax } from "./account_tax.data.js";
import { AccountTaxGroup } from "./account_tax_group.data.js";
import { BarcodeNomenclature } from "./barcode_nomenclature.data.js";
import { DecimalPrecision } from "./decimal_precision.data.js";
import { IrModuleModule } from "./ir_module_module.data.js";
import { IrSequence } from "./ir_sequence.data.js";
import { PosBill } from "./pos_bill.data.js";
import { PosCategory } from "./pos_category.data.js";
import { PosConfig } from "./pos_config.data.js";
import { PosNote } from "./pos_note.data.js";
import { PosOrder } from "./pos_order.data.js";
import { PosOrderLine } from "./pos_order_line.data.js";
import { PosPackOperationLot } from "./pos_pack_operation_lot.data.js";
import { PosPayment } from "./pos_payment.data.js";
import { PosPaymentMethod } from "./pos_payment_method.data.js";
import { PosPreset } from "./pos_preset.data.js";
import { PosPrinter } from "./pos_printer.data.js";
import { PosSession } from "./pos_session.data.js";
import { ProductAttribute } from "./product_attribute.data.js";
import { ProductAttributeCustomValue } from "./product_attribute_custom_value.data.js";
import { ProductAttributeValue } from "./product_attribute_value.data.js";
import { ProductCategory } from "./product_category.data.js";
import { ProductCombo } from "./product_combo.data.js";
import { ProductComboItem } from "./product_combo_item.data.js";
import { ProductPricelist } from "./product_pricelist.data.js";
import { ProductPricelistItem } from "./product_pricelist_item.data.js";
import { ProductProduct } from "./product_product.data.js";
import { ProductTag } from "./product_tag.data.js";
import { ProductTemplate } from "./product_template.data.js";
import { ProductTemplateAttributeExclusion } from "./product_template_attribute_exclusion.data.js";
import { ProductTemplateAttributeLine } from "./product_template_attribute_line.data.js";
import { ProductTemplateAttributeValue } from "./product_template_attribute_value.data.js";
import { ProductUom } from "./product_uom.data.js";
import { ResCompany } from "./res_company.data.js";
import { ResCountry } from "./res_country.data.js";
import { ResCountryState } from "./res_country_state.data.js";
import { ResCurrency } from "./res_currency.data.js";
import { ResLang } from "./res_lang.data.js";
import { ResPartner } from "./res_partner.data.js";
import { ResUsers } from "./res_users.data.js";
import { ResourceCalendar } from "./resource_calendar.data.js";
import { ResourceCalendarAttendance } from "./resource_calendar_attendance.js";
import { StockPickingType } from "./stock_picking_type.data.js";
import { StockRoute } from "./stock_route.data.js";
import { StockWarehouse } from "./stock_warehouse.data.js";
import { UomUom } from "./uom_uom.data.js";

export const hootPosModels = [
    ResCountry,
    ResCountryState,
    ResCurrency,
    ResCompany,
    ResPartner,
    ResUsers,
    ResLang,
    PosSession,
    PosConfig,
    PosPreset,
    ResourceCalendarAttendance,
    PosOrder,
    PosOrderLine,
    PosPackOperationLot,
    PosPayment,
    PosPaymentMethod,
    PosPrinter,
    PosCategory,
    PosBill,
    AccountTax,
    AccountTaxGroup,
    AccountMove,
    ProductCategory,
    ProductTemplate,
    ProductProduct,
    ProductAttribute,
    ProductAttributeValue,
    ProductAttributeCustomValue,
    ProductTemplateAttributeLine,
    ProductTemplateAttributeValue,
    ProductTemplateAttributeExclusion,
    ProductCombo,
    ProductComboItem,
    ProductUom,
    ProductTag,
    ProductPricelist,
    ProductPricelistItem,
    DecimalPrecision,
    StockWarehouse,
    StockRoute,
    UomUom,
    AccountCashRounding,
    AccountFiscalPosition,
    StockPickingType,
    IrSequence,
    PosNote,
    IrModuleModule,
    AccountJournal,
    ResourceCalendar,
    BarcodeNomenclature,
];

export const definePosModels = () => {
    const posModelNames = hootPosModels.map(
        (modelClass) => modelClass.prototype.constructor._name,
    );
    const modelsFromMail = Object.values(mailModels).filter(
        (modelClass) => !posModelNames.includes(modelClass.prototype.constructor._name),
    );
    onRpc("/pos/ping", () => {});
    defineModels([...modelsFromMail, ...hootPosModels]);
};
