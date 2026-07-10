// @ts-check

import { before, withFetch } from "@odoo/hoot";
import { loadBundle } from "@web/core/assets";
import { loadChartJS } from "@web/core/lib/chartjs";
import { loadFullCalendar } from "@web/core/lib/fullcalendar";

import * as _fields from "./_framework/mock_server/mock_fields.js";
import * as _models from "./_framework/mock_server/mock_model.js";
import { IrAttachment } from "./_framework/mock_server/mock_models/ir_attachment.js";
import { IrHttp } from "./_framework/mock_server/mock_models/ir_http.js";
import { IrModel } from "./_framework/mock_server/mock_models/ir_model.js";
import { IrModelAccess } from "./_framework/mock_server/mock_models/ir_model_access.js";
import { IrModelFields } from "./_framework/mock_server/mock_models/ir_model_fields.js";
import { IrModuleCategory } from "./_framework/mock_server/mock_models/ir_module_category.js";
import { IrRule } from "./_framework/mock_server/mock_models/ir_rule.js";
import { IrUiView } from "./_framework/mock_server/mock_models/ir_ui_view.js";
import { ResCompany } from "./_framework/mock_server/mock_models/res_company.js";
import { ResCountry } from "./_framework/mock_server/mock_models/res_country.js";
import { ResCurrency } from "./_framework/mock_server/mock_models/res_currency.js";
import { ResGroups } from "./_framework/mock_server/mock_models/res_groups.js";
import { ResGroupsPrivilege } from "./_framework/mock_server/mock_models/res_groups_privilege.js";
import { ResLang } from "./_framework/mock_server/mock_models/res_lang.js";
import { ResPartner } from "./_framework/mock_server/mock_models/res_partner.js";
import { ResUsers } from "./_framework/mock_server/mock_models/res_users.js";
import { ResUsersSettings } from "./_framework/mock_server/mock_models/res_users_settings.js";
import {
    defineModels,
    setDefaultMockModels,
    setDefaultMockRoute,
} from "./_framework/mock_server/mock_server.js";
import { globalCachedFetch } from "./_framework/module_set.hoot.js";

/**
 * @typedef {import("./_framework/dom_test_helpers").DragAndDropOptions} DragAndDropOptions
 * @typedef {import("./_framework/mock_server/mock_fields").FieldType} FieldType
 * @typedef {import("./_framework/mock_server/mock_server").MockServerEnvironment} MockServerEnvironment
 * @typedef {import("./_framework/mock_server/mock_model").ModelRecord} ModelRecord
 */

/**
 * @template T
 * @typedef {import("./_framework/mock_server/mock_server").KwArgs<T>} KwArgs
 */

/**
 * @template T
 * @typedef {import("./_framework/mock_server/mock_server").RouteCallback<T>} RouteCallback
 */

export { asyncStep, waitForSteps } from "./_framework/async_step.js";
export {
    findComponent,
    getDropdownMenu,
    mountWithCleanup,
    waitUntilIdle,
} from "./_framework/component_test_helpers.js";
export {
    contains,
    defineStyle,
    editAce,
    sortableDrag,
} from "./_framework/dom_test_helpers.js";
export {
    clearRegistry,
    getMockEnv,
    getService,
    makeDialogMockEnv,
    makeMockEnv,
    mockService,
    restoreRegistry,
} from "./_framework/env_test_helpers.js";
export {
    clickKanbanLoadMore,
    clickKanbanRecord,
    createKanbanRecord,
    discardKanbanRecord,
    editKanbanColumnName,
    editKanbanRecord,
    editKanbanRecordQuickCreateInput,
    getKanbanColumn,
    getKanbanColumnDropdownMenu,
    getKanbanColumnTooltips,
    getKanbanCounters,
    getKanbanProgressBars,
    getKanbanRecord,
    getKanbanRecordTexts,
    quickCreateKanbanColumn,
    quickCreateKanbanRecord,
    toggleKanbanColumnActions,
    toggleKanbanRecordDropdown,
    validateKanbanColumn,
    validateKanbanRecord,
} from "./_framework/kanban_test_helpers.js";
export {
    Command,
    registerInlineViewArchs,
} from "./_framework/mock_server/mock_model.js";
export {
    authenticate,
    defineActions,
    defineMenus,
    defineModels,
    defineParams,
    logout,
    makeMockServer,
    MockServer,
    onRpc,
    stepAllNetworkCalls,
    withUser,
} from "./_framework/mock_server/mock_server.js";
export {
    getKwArgs,
    makeKwArgs,
    makeServerError,
    MockServerError,
    unmakeKwArgs,
} from "./_framework/mock_server/mock_server_utils.js";
export { serverState } from "./_framework/mock_server_state.hoot.js";
export { patchWithCleanup } from "./_framework/patch_test_helpers.js";
export { preventResizeObserverError } from "./_framework/resize_observer_error_catcher.js";
export {
    editFavorite,
    editFavoriteName,
    editPager,
    editSearch,
    getButtons,
    getFacetTexts,
    getMenuItemTexts,
    getPagerLimit,
    getPagerValue,
    getVisibleButtons,
    isItemSelected,
    isOptionSelected,
    mountWithSearch,
    openAddCustomFilterDialog,
    pagerNext,
    pagerPrevious,
    removeFacet,
    saveAndEditFavorite,
    saveFavorite,
    selectGroup,
    switchView,
    toggleActionMenu,
    toggleFavoriteMenu,
    toggleFilterMenu,
    toggleGroupByMenu,
    toggleMenu,
    toggleMenuItem,
    toggleMenuItemOption,
    toggleSaveFavorite,
    toggleSearchBarMenu,
    validateSearch,
} from "./_framework/search_test_helpers.js";
export { swipeLeft, swipeRight } from "./_framework/touch_helpers.js";
export {
    allowTranslations,
    installLanguages,
    patchTranslations,
} from "./_framework/translation_test_helpers.js";
export {
    clickButton,
    clickCancel,
    clickFieldDropdown,
    clickFieldDropdownItem,
    clickModalButton,
    clickSave,
    clickViewButton,
    editSelectMenu,
    expectMarkup,
    fieldInput,
    hideTab,
    mountView,
    mountViewInDialog,
    parseViewProps,
    selectFieldDropdownItem,
} from "./_framework/view_test_helpers.js";
export {
    mountWebClient,
    useTestClientAction,
} from "./_framework/webclient_test_helpers.js";

export function defineWebModels() {
    return defineModels(webModels);
}

/**
 * @param {string} bundleName
 */
export function preloadBundle(bundleName) {
    before(async function preloadBundle() {
        await withFetch(globalCachedFetch, () => loadBundle(bundleName));
    });
}

/**
 * Preload Chart.js (+ its luxon date adapter) once before a suite, the way
 * `preloadBundle("web.chartjs_lib")` used to — except the libs are now real ES
 * modules pulled through the import map by `loadChartJS`, not a classic-script
 * bundle that assigned `window.Chart`.
 */
export function preloadChartJS() {
    before(async function preloadChartJS() {
        await withFetch(globalCachedFetch, () => loadChartJS());
    });
}

/**
 * Preload FullCalendar (+ locales, skeleton CSS) once before a suite, the way
 * `preloadBundle("web.fullcalendar_lib")` used to — now via the `loadFullCalendar`
 * ESM loader instead of a classic-script bundle assigning `window.FullCalendar`.
 */
export function preloadFullCalendar() {
    before(async function preloadFullCalendar() {
        await withFetch(globalCachedFetch, () => loadFullCalendar());
    });
}

/**
 * @param {string} dataURI
 * @returns {Blob}
 */
export function dataURItoBlob(dataURI) {
    const binary = atob(dataURI.split(",")[1]);
    const array = [];
    const mimeString = dataURI.split(",")[0].split(":")[1].split(";")[0];
    for (let i = 0; i < binary.length; i++) {
        array.push(binary.charCodeAt(i));
    }
    return new Blob([new Uint8Array(array)], { type: mimeString });
}

export const fields = _fields;
export const models = _models;

export const webModels = {
    IrHttp,
    IrAttachment,
    IrModel,
    IrModelAccess,
    IrModelFields,
    IrModuleCategory,
    IrRule,
    IrUiView,
    ResCompany,
    ResCountry,
    ResCurrency,
    ResGroupsPrivilege,
    ResGroups,
    ResLang,
    ResPartner,
    ResUsers,
    ResUsersSettings,
};

// Extra-narrow seed of routing-infrastructure models. Tests that render
// avatars or images call `/web/image/<model>/<id>/<field>` which routes
// through `ir.http.binary_content`; without IrHttp registered, those tests
// fail with "Cannot find a definition for model 'ir.http'" plus cascade
// HootTimingError. We deliberately do NOT seed IrAttachment because some
// tests assert against the missing-model error path for upload flows
// (html_editor's link popover file upload), and broader webModels are
// avoided because they leak record presence into search-panel/webclient
// tests' record-absence assertions.
setDefaultMockModels({ IrHttp });

// Default mock for the mail bootstrap routes.
//
// The mail store_service (``mail/static/src/core/common/store_service.js``)
// eagerly fires ``/mail/data`` (or ``/mail/action``) on WebClient mount to
// pre-seed its in-memory store. Core unit tests that mount WebClient or
// CommandPalette without importing ``mail_test_helpers`` then hit
// ``Unimplemented server route`` and Hoot counts the resulting RPC_ERROR as
// an "unverified error" — failing the test for a side-effect that has
// nothing to do with what it's asserting.
//
// Registering an empty handler via ``setDefaultMockRoute`` makes the routes
// "known" so the bootstrap returns nothing and produces no error. Mail
// tests can still register their own handler via ``onRpc(...)``; the later
// per-test registration shadows this default because ``_defineParams`` is
// ``mode: "add"`` in ``onRpc``.
//
// ``onRpc`` at module load would NOT work here — it wraps the registration
// in ``before(...)`` which is suite-scoped and silently no-ops outside a
// describe block. ``setDefaultMockRoute`` folds the handler into the
// runner-level params snapshot in ``getCurrentParams``, which IS picked up
// when each job starts.
//
// We mock both routes because the choice between them is controlled at
// runtime by ``store_service.fetchReadonly`` and tests don't pin it.
setDefaultMockRoute("/mail/data", () => ({}));
setDefaultMockRoute("/mail/action", () => ({}));
