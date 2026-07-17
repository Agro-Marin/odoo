/** @odoo-module native */
import { PosData } from "@point_of_sale/app/services/data_service";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";

// These overrides only apply inside the self-order app, which is the only
// context that populates `session.data` (config_id, self_ordering_mode, ...).
// The whole patch is co-loaded into `web.assets_unit_tests_setup` for
// pos_self_order's own unit tests, so it must stay inert when another module's
// POS unit test runs with pos_self_order co-installed (no self-order session):
// every override defers to base PosData when `session.data` is absent, mirroring
// the self_ordering_mode gating the IndexedDB overrides already do.
const isSelfOrder = () => Boolean(session.data);
const isSelfOrderMobile = () => session.data?.self_ordering_mode === "mobile";

export const unpatchSelf = patch(PosData.prototype, {
    async loadInitialData() {
        if (!isSelfOrder()) {
            return super.loadInitialData(...arguments);
        }
        const configId = session.data.config_id;
        return await rpc(`/pos-self/data/${parseInt(configId)}`, {
            access_token: odoo.access_token,
        });
    },
    async loadFieldsAndRelations() {
        if (!isSelfOrder()) {
            return super.loadFieldsAndRelations(...arguments);
        }
        const configId = session.data.config_id;
        return await rpc(`/pos-self/relations/${parseInt(configId)}`);
    },
    get databaseName() {
        return isSelfOrder() ? `pos-self-order-${odoo.access_token}` : super.databaseName;
    },
    async initializeDeviceIdentifier() {
        return isSelfOrder() ? false : super.initializeDeviceIdentifier(...arguments);
    },
    initIndexedDB() {
        if (!isSelfOrder()) {
            return super.initIndexedDB(...arguments);
        }
        return isSelfOrderMobile() ? super.initIndexedDB(...arguments) : true;
    },
    initListeners() {
        if (!isSelfOrder()) {
            return super.initListeners(...arguments);
        }
        return isSelfOrderMobile() ? super.initListeners(...arguments) : true;
    },
    synchronizeLocalDataInIndexedDB() {
        if (!isSelfOrder()) {
            return super.synchronizeLocalDataInIndexedDB(...arguments);
        }
        return isSelfOrderMobile()
            ? super.synchronizeLocalDataInIndexedDB(...arguments)
            : true;
    },
    async getCachedServerDataFromIndexedDB() {
        if (!isSelfOrder()) {
            return await super.getCachedServerDataFromIndexedDB(...arguments);
        }
        return isSelfOrderMobile()
            ? await super.getCachedServerDataFromIndexedDB(...arguments)
            : {};
    },
    async getLocalDataFromIndexedDB() {
        if (!isSelfOrder()) {
            return await super.getLocalDataFromIndexedDB(...arguments);
        }
        return isSelfOrderMobile()
            ? await super.getLocalDataFromIndexedDB(...arguments)
            : {};
    },
    async missingRecursive(recordMap) {
        return isSelfOrder() ? recordMap : await super.missingRecursive(...arguments);
    },
    async checkAndDeleteMissingOrders(results) {
        if (!isSelfOrder()) {
            return await super.checkAndDeleteMissingOrders(...arguments);
        }
    },
    async deleteRecordsInIndexedDB(model, ids) {
        if (!isSelfOrder()) {
            return await super.deleteRecordsInIndexedDB(...arguments);
        }
        return isSelfOrderMobile()
            ? await super.deleteRecordsInIndexedDB(...arguments)
            : true;
    },
});
