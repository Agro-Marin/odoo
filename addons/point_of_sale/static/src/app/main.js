/** @odoo-module native */
import { mount, reactive, whenReady } from "@odoo/owl";
import { Loader } from "@point_of_sale/app/components/loader/loader";
import { Chrome } from "@point_of_sale/app/pos_app";
import { hasTouch } from "@web/core/browser/feature_detection";
import { makeLogger } from "@web/core/debug/debug_logger";
import { localization } from "@web/core/l10n/localization";
import { publishOdooInfo } from "@web/core/odoo_info";
import { getTemplate } from "@web/core/templates";
import { _t, appTranslateFn } from "@web/core/translation";
import { SUPERUSER_ID, user } from "@web/core/user";
import { mountComponent } from "@web/env";

const loader = reactive({ isShown: true, error: false });
const log = makeLogger("pos.boot");
whenReady(() => {
    mount(Loader, document.body, {
        getTemplate,
        props: { loader },
        translatableAttributes: ["data-tooltip"],
        translateFn: appTranslateFn,
    });
});

(async function startPosApp() {
    publishOdooInfo();
    await whenReady();
    const endBoot = log.perf("startPosApp");
    log.lifecycle("startPosApp", () => ({
        config: odoo.pos_config_id,
        session: odoo.pos_session_id,
        debug: odoo.debug,
        fromBackend: Boolean(odoo.from_backend),
    }));
    try {
        const app = await mountComponent(Chrome, document.body, {
            name: "Odoo Point of Sale",
            props: { disableLoader: () => (loader.isShown = false) },
        });
        endBoot({ services: Object.keys(app.env.services).length });
        window.addEventListener("beforeunload", function (event) {
            log.lifecycle("[beforeunload]", () => ({
                offline: app.env.services.pos_data.network.offline,
                unsyncedPaid:
                    app.env.services.pos_data.localUnsyncedPaidOrderUuids.size,
            }));
            if (app.env.services.pos_data.network.offline) {
                const confirmationMessage = _t(
                    "You are currently offline. Reloading the page may cause you to lose unsaved data.",
                );
                event.returnValue = confirmationMessage;
                return confirmationMessage;
            }
            if (app.env.services.pos_data.localUnsyncedPaidOrderUuids.size > 0) {
                const confirmationMessage = _t(
                    "Some paid orders have not been saved yet. Closing or reloading now may cause data loss.",
                );
                event.returnValue = confirmationMessage;
                return confirmationMessage;
            }
        });
        const classList = document.body.classList;
        if (localization.direction === "rtl") {
            classList.add("o_rtl");
        }
        if (user.userId === SUPERUSER_ID) {
            classList.add("o_is_superuser");
        }
        if (hasTouch()) {
            classList.add("o_touch_device");
            classList.add("o_mobile_overscroll");
            document.documentElement.classList.add("o_mobile_overscroll");
        }

        registerServiceWorker();
    } catch (e) {
        endBoot({ error: e?.constructor?.name, message: e?.message });
        loader.error = e;
        throw e;
    }
})();

function registerServiceWorker() {
    const urlsToCache = JSON.parse(odoo.urls_to_cache);
    urlsToCache.push("/web/static/lib/zxing-library/zxing-library.js");
    log.lifecycle("registerServiceWorker", () => ({
        supported: Boolean(navigator.serviceWorker),
        urlsToCache: urlsToCache.length,
    }));

    navigator.serviceWorker?.register("/pos/service-worker.js").then((registration) => {
        const worker =
            registration.installing || registration.waiting || registration.active;
        log.lifecycle("registerServiceWorker: registered", () => ({
            state: worker?.state,
        }));
        worker.postMessage({ urlsToCache });
    });
}
