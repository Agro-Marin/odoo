/** @odoo-module native */

// The tax computation engine physically lives in the ``base_tax`` module (the
// canonical mirror of ``base_tax/models/account_tax.py``).  This module keeps
// the historical ``@account/helpers/account_tax`` import path working as a
// stable public API: account, point_of_sale, the l10n_* patchers and enterprise
// all import ``accountTaxHelpers`` from here, and upstream Odoo keeps the engine
// under ``account`` — so re-exporting (rather than renaming every importer)
// avoids breaking those consumers and keeps upstream syncs conflict-free.
export { accountTaxHelpers } from "@base_tax/helpers/account_tax";
