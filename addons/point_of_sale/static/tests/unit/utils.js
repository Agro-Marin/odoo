import { after, expect } from "@odoo/hoot";
import { animationFrame, tick, waitFor, waitUntil } from "@odoo/hoot-dom";
import { Deferred } from "@odoo/hoot-mock";
import { onMounted } from "@odoo/owl";
import { PosDataService } from "@point_of_sale/app/services/data_service";
import { posService } from "@point_of_sale/app/services/pos_store";
import { uuidv4 } from "@point_of_sale/utils";
import {
    getService,
    makeDialogMockEnv,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/ui/main_components_container";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";

const { DateTime } = luxon;

export const setupPosEnv = async () => {
    odoo.pos_session_id = 1;
    odoo.pos_config_id = 1;
    odoo.from_backend = 0;
    odoo.access_token = uuidv4();
    odoo.info = {
        db: `pos-${uuidv4()}`,
        isEnterprise: true,
    };

    const services = registry.category("services");
    services.add("pos_data", PosDataService, { force: true });
    services.add("pos", posService, { force: true });

    await makeDialogMockEnv();
    const store = getService("pos");

    after(async () => {
        store.syncAllOrdersDebounced?.cancel?.();
        await store.pushOrderMutex?.getUnlockedDef?.();
    });

    store.setCashier(store.user);
    patchWithCleanup(user, {
        checkAccessRight: (model, operation) =>
            operation === "create" && model === "product.product",
    });
    return store;
};

export const getFilledOrder = async (store, data = {}) => {
    const order = store.addNewOrder(data);
    const product1 = store.models["product.template"].get(5);
    const product2 = store.models["product.template"].get(6);
    const date = DateTime.now();
    order.write_date = date;
    order.create_date = date;

    await store.addLineToOrder(
        {
            product_tmpl_id: product1,
            qty: 3,
            write_date: date,
            create_date: date,
        },
        order,
    );
    await store.addLineToOrder(
        {
            product_tmpl_id: product2,
            qty: 2,
            write_date: date,
            create_date: date,
        },
        order,
    );
    store.addPendingOrder([order.id]);
    return order;
};

export async function waitUntilOrdersSynced(store, options) {
    await waitUntil(() => !store.syncingOrders.size, options);
    await tick();
}

export const mountPosDialog = async (component, props) => {
    patchDialogComponent(component);
    const dialog = getService("dialog");
    const root = await mountWithCleanup(MainComponentsContainer);
    const deferred = new Deferred();

    const getComponentInstance = (root) => {
        const flattenedChildren = (comp, acc = {}) => {
            const array = Object.values(comp.children);
            for (const child of array) {
                acc[child.name] = child;
                flattenedChildren(child, acc);
            }
            return acc;
        };
        const components = flattenedChildren(root);
        return components[component.name];
    };

    dialog.add(component, {
        ...props,
        onMounted() {
            const dialogComponent = getComponentInstance(root.__owl__);
            deferred.resolve(dialogComponent.component);
        },
    });
    return await deferred;
};

export const patchDialogComponent = (component) => {
    component.props = [...component.props, "onMounted?"];
    patch(component.prototype, {
        setup() {
            super.setup();

            onMounted(() => {
                this.props.onMounted && this.props.onMounted();
            });
        },
    });
};

export const expectFormattedPrice = (value, expected) => {
    expect(value).toBe(expected.replaceAll(" ", "\u00a0"));
};

export const dialogActions = async (action, steps = []) => {
    await mountWithCleanup(MainComponentsContainer);
    const promise = new Promise((resolve) => {
        const call = async (fn) => {
            const result = await fn();
            resolve(result);
        };
        call(action);
    });

    await waitFor(".o_dialog");

    for (const step of steps) {
        await step();
        await animationFrame();
    }

    return await promise;
};
