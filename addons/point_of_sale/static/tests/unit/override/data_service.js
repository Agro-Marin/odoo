import { PosData } from "@point_of_sale/app/services/data_service";
import { patch } from "@web/core/utils/patch";

patch(PosData.prototype, {
    setup() {
        this.indexedDB = {
            delete: async () => ({}),
            create: async () => ({}),
            reset: async () => ({}),
            readAll: async () => ({}),
        };
        return super.setup(...arguments);
    },
    initIndexedDB() {
        return true;
    },
    initListeners() {
        return true;
    },
    synchronizeLocalDataInIndexedDB() {
        return true;
    },
    async getCachedServerDataFromIndexedDB() {
        return {};
    },
    async getLocalDataFromIndexedDB() {
        return {};
    },
});
