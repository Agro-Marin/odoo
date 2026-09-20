/** @odoo-module native */
import { patch } from "@web/core/utils/patch";

import {
    ApplyConfiguratorScreen,
    Configurator,
    FeaturesSelectionScreen,
    ROUTES,
} from "@website/client_actions/configurator/configurator";
import { ProductPageSelectionScreen } from "@website_sale/js/client_actions/configurator/productPageSelectionScreen";
import { ShopPageSelectionScreen } from "@website_sale/js/client_actions/configurator/shopPageSelectionScreen";

ROUTES.shopPageSelectionScreen = 50;
ROUTES.productPageSelectionScreen = 55;

patch(ApplyConfiguratorScreen.prototype, {
    /**
     * @override
     */
    getConfigurationData() {
        const data = super.getConfigurationData(...arguments);
        return Object.assign(data, {
            shop_page_style_option: this.state.selectedShopPageStyleOption,
            product_page_style_option: this.state.selectedProductPageStyleOption,
        });
    },
});

patch(FeaturesSelectionScreen, {
    /**
     * @override
     */
    nextStep() {
        return ROUTES.shopPageSelectionScreen;
    },
});

patch(Configurator, {
    components: {
        ...Configurator.components,
        ShopPageSelectionScreen,
        ProductPageSelectionScreen,
    },
});

patch(Configurator.prototype, {
    /**
     * @override
     */
    get currentComponent() {
        if (this.state.currentStep === ROUTES.shopPageSelectionScreen) {
            return ShopPageSelectionScreen;
        }
        if (this.state.currentStep === ROUTES.productPageSelectionScreen) {
            return ProductPageSelectionScreen;
        }
        return super.currentComponent;
    },

    /**
     * @override
     */
    async getInitialState() {
        const initState = await super.getInitialState(...arguments);
        initState.selectedShopPageStyleOption = undefined;
        initState.selectedProductPageStyleOption = undefined;
        return initState;
    },
});
