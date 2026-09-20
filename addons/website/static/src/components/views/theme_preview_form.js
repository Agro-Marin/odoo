/** @odoo-module native */
import { onMounted, useEnv, useSubEnv } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { FormController, formView } from "@web/views/form";
import { ViewButton } from "@web/views/view_button";

const log = makeLogger("website.view.theme_preview");

export function useLoaderOnClick() {
    const website = useService("website");
    const orm = useService("orm");
    const action = useService("action");
    const env = useEnv();
    const previousOnClickViewButton = env.onClickViewButton;
    useSubEnv({
        async onClickViewButton(params) {
            const name = params.clickParams.name;
            log.logic("onClickViewButton", { name });
            if (["button_refresh_theme", "button_choose_theme"].includes(name)) {
                website.invalidateSnippetCache = true;
                website.showLoader({ showTips: name !== "button_refresh_theme" });
                try {
                    const resParams = params.getResParams();
                    const endTheme = log.perf("theme button call", () => ({
                        name,
                        resModel: resParams.resModel,
                        resId: resParams.resId,
                    }));
                    const callback = await orm.silent.call(resParams.resModel, name, [
                        [resParams.resId],
                    ]);
                    endTheme(() => ({ callbackTag: callback?.tag }));
                    let keepLoader = false;
                    if (callback) {
                        callback.target = "main";
                        const endAction = log.perf("theme button doAction");
                        await action.doAction(callback);
                        endAction();
                        if (callback.tag === "website_preview") {
                            keepLoader = true;
                        }
                    }
                    log.logic("theme button done", { keepLoader });
                    if (!keepLoader) {
                        website.hideLoader();
                    }
                } catch (error) {
                    log.logic("theme button failed", () => ({
                        name,
                        message: error?.message,
                    }));
                    website.hideLoader();
                    throw error;
                }
            } else {
                return previousOnClickViewButton(...arguments);
            }
        },
    });
}

class ThemePreviewFormController extends FormController {
    static components = { ...FormController.components, ViewButton };
    static template = "website.ThemePreviewFormController";
    /**
     * @override
     */
    setup() {
        super.setup();
        useLifecycleLog(log);
        useLoaderOnClick();

        onMounted(() => {
            setTimeout(() => {
                log.lifecycle("ThemePreviewFormController auto-click choose theme");
                document.querySelector('button[name="button_choose_theme"]')?.click();
            }, 0);
        });
    }
    /**
     * @override
     */
    get className() {
        return { ...super.className, o_view_form_theme_preview_controller: true };
    }
    back() {
        this.env.config.historyBack();
    }
}

class ThemePreviewFormControlPanel extends ControlPanel {
    static template = "website.ThemePreviewForm.ControlPanel";
    onMobileClick() {
        log.logic("ThemePreviewFormControlPanel switch mode", { mode: "mobile" });
        this.env.bus.trigger("THEME_PREVIEW:SWITCH_MODE", { mode: "mobile" });
    }
    onDesktopClick() {
        log.logic("ThemePreviewFormControlPanel switch mode", { mode: "desktop" });
        this.env.bus.trigger("THEME_PREVIEW:SWITCH_MODE", { mode: "desktop" });
    }
    back() {
        this.env.config.historyBack();
    }
}

const ThemePreviewFormView = {
    ...formView,
    Controller: ThemePreviewFormController,
    ControlPanel: ThemePreviewFormControlPanel,
};

registry.category("views").add("theme_preview_form", ThemePreviewFormView);
