import { expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

import { QrCodeCustomerDisplay } from "@point_of_sale/app/customer_display/customer_display_qr_code_popup";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

const screen = (values) => ({
    availLeft: 0,
    availTop: 0,
    availWidth: 1280,
    availHeight: 720,
    ...values,
});

test("the customer display is placed on a detected second screen", async () => {
    await setupPosEnv();
    const current = screen({});
    patchWithCleanup(window, {
        getScreenDetails: async () => ({
            currentScreen: current,
            screens: [
                current,
                screen({
                    availLeft: 1280,
                    availTop: 40,
                    availWidth: 1920,
                    availHeight: 1080,
                }),
            ],
        }),
    });

    const { windowFeatures, usedFallback } =
        await QrCodeCustomerDisplay.prototype.getScreenFeatures();
    expect(usedFallback).toBe(false);
    expect(windowFeatures).toBe("left=1280,top=40,width=1920,height=1080");
});

test("a single screen keeps the customer display on this device", async () => {
    await setupPosEnv();
    const current = screen({});
    patchWithCleanup(window, {
        getScreenDetails: async () => ({
            currentScreen: current,
            screens: [current],
        }),
    });

    const { windowFeatures, usedFallback } =
        await QrCodeCustomerDisplay.prototype.getScreenFeatures();
    expect(usedFallback).toBe(false);
    expect(windowFeatures).toBe("width=800,height=600,left=200,top=200");
});

test("a refused screen permission falls back and says so", async () => {
    await setupPosEnv();
    patchWithCleanup(window, {
        getScreenDetails: async () => {
            throw new Error("Permission denied");
        },
    });

    const { windowFeatures, usedFallback } =
        await QrCodeCustomerDisplay.prototype.getScreenFeatures();
    expect(usedFallback).toBe(true);
    expect(windowFeatures).toBe("width=800,height=600,left=200,top=200");
});
