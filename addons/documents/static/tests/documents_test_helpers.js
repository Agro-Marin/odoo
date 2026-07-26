import { defineModels } from "@web/../tests/web_test_helpers";
import { registerMailMockRoutes } from "@mail/../tests/mock_server/mail_mock_server";
import { DocumentsModels } from "@documents/../tests/helpers/data";

/**
 * The documents test model registry.
 *
 * This module used to declare its own `{ ...mailModels, ResUsers }`, which drifted
 * from `helpers/data.js`'s `DocumentsModels`: one had the ResUsers store patch but
 * none of the documents models, the other had every model but no ResUsers. Tests
 * picked whichever they imported, and the ones on the second list silently lost
 * `store.hasDocumentsUserGroup`. There is now one list; this is an alias.
 */
export const documentsModels = DocumentsModels;

/**
 * Define the documents models AND bind mail's mock routes to the calling file.
 *
 * `mail_mock_server.js` registers `/mail/data` & co. at module level, which binds
 * them to whichever test file's suite happened to import it first; every other
 * file loses them unless `registerMailMockRoutes()` replays them (see that
 * function's docstring). `defineMailModels()` does this for mail's own tests --
 * documents spreads `mailModels` into `defineModels()` instead, which registers
 * the *models* but never the *routes*.
 *
 * The result was silent: `/mail/data` went unmocked, so the store never received
 * activity groups, inbox notifications or chatter data, and every mail-driven
 * surface rendered empty while looking like a broken component. Call this from
 * the top level of each documents test file rather than `defineModels(...)`.
 */
export function defineDocumentsModels() {
    registerMailMockRoutes();
    return defineModels(documentsModels);
}
