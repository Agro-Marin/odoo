/** @odoo-module native */

// The tax computation engine lives in ``base_tax`` (the JS mirror of
// ``base_tax/models/account_tax.py``). Re-exporting it keeps the historical
// ``@account/helpers/account_tax`` path working for account, point_of_sale, the
// l10n_* patchers and enterprise, and keeps upstream syncs (which keep the
// engine under ``account``) conflict-free.
export { accountTaxHelpers } from "@base_tax/helpers/account_tax";
