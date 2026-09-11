/** @odoo-module native */
import { onMounted, useEnv, useSubEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { FormController, formView } from "@web/views/form";
import { ViewButton } from "@web/views/view_button";

export function useLoaderOnClick() {
    const website = useService("website");
    const orm = useService("orm");
    const action = useService("action");
    const env = useEnv();
    const previousOnClickViewButton = env.onClickViewButton;
    useSubEnv({
        async onClickViewButton(params) {
            const name = params.clickParams.name;
            if (["button_refresh_theme", "button_choose_theme"].includes(name)) {
                website.invalidateSnippetCache = true;
                website.showLoader({ showTips: name !== "button_refresh_theme" });
                try {
                    const resParams = params.getResParams();
                    const callback = await orm.silent.call(resParams.resModel, name, [
                        [resParams.resId],
                    ]);
                    let keepLoader = false;
                    if (callback) {
                        callback.target = "main";
                        await action.doAction(callback);
                        if (callback.tag === "website_preview") {
                            keepLoader = true;
                        }
                    }
                    if (!keepLoader) {
                        website.hideLoader();
                    }
                } catch (error) {
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
        useLoaderOnClick();

        onMounted(() => {
            setTimeout(() => {
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
        this.env.bus.trigger("THEME_PREVIEW:SWITCH_MODE", { mode: "mobile" });
    }
    onDesktopClick() {
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
