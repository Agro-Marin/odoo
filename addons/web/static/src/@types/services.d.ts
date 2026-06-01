declare module "services" {
    import { ServicesRegistryShape } from "registries";

    // Public services
    import { publicInteractionService } from "@web/public/interaction_service";

    // Domain services
    import { commandService } from "@web/services/commands/command_service";
    import { errorService } from "@web/services/error_service";
    import { fieldService } from "@web/services/field_service";
    import { fileUploadService } from "@web/services/file_upload_service";
    import { formDialogStackService } from "@web/services/form_dialog_stack_service";
    import { frequentEmojiService } from "@web/services/frequent_emoji_service";
    import { hotkeyService } from "@web/services/hotkeys/hotkey_service";
    import { httpService } from "@web/services/http_service";
    import { localizationService } from "@web/services/localization_service";
    import { multiCompanyRecoveryService } from "@web/services/multi_company_recovery_service";
    import { nameService } from "@web/services/name_service";
    import { ormService } from "@web/services/orm_service";
    import { pwaService } from "@web/services/pwa/pwa_service";
    import { resultSetCacheInvalidatorService } from "@web/services/result_set_cache_invalidator_service";
    import { scssErrorNotificationService } from "@web/services/scss_error_display";
    import { slowRpcService } from "@web/services/slow_rpc_service";
    import { sortableService } from "@web/services/sortable_service";
    import { titleService } from "@web/services/title_service";
    import { treeProcessorService } from "@web/services/tree_processor_service";
    import { webVitalsService } from "@web/services/web_vitals/web_vitals_service";
    import { allowedQwebExpressionsService } from "@web/fields/dynamic_placeholder_popover";
    import { datetimePickerService } from "@web/components/datetime/datetime_picker_service";

    // UI overlay services
    import { bottomSheetService } from "@web/ui/bottom_sheet/bottom_sheet_service";
    import { dialogService } from "@web/ui/dialog/dialog_service";
    import { effectService } from "@web/ui/effects/effect_service";
    import { notificationService } from "@web/ui/notification/notification_service";
    import { overlayService } from "@web/ui/overlay/overlay_service";
    import { popoverService } from "@web/ui/popover/popover_service";
    import { tooltipService } from "@web/ui/tooltip/tooltip_service";
    import { uiService } from "@web/ui/block/ui_service";

    // View services
    import { demoDataService } from "@web/views/settings/widgets/demo_data_service";
    import { userInviteService } from "@web/views/settings/widgets/user_invite_service";
    import { viewService } from "@web/views/view_service";

    // Webclient services
    import { actionService } from "@web/webclient/actions/action_service";
    import { currencyService } from "@web/webclient/currency_service";
    import { densityService } from "@web/webclient/density/density_service";
    import { lazySession } from "@web/webclient/session_service";
    import { menuService } from "@web/webclient/menus/menu_service";
    import { profilingService } from "@web/webclient/debug/profiling/profiling_service";
    import { reloadCompanyService } from "@web/webclient/reload_company_service";
    import { shareTargetService } from "@web/webclient/share_target/share_target_service";

    type ExtractServiceFactory<T extends ServicesRegistryShape> = Awaited<ReturnType<T["start"]>>;
    export type ServiceFactories = {
        [P in keyof Services]: ExtractServiceFactory<Services[P]>;
    };

    export interface Services {
        action: typeof actionService;
        allowed_qweb_expressions: typeof allowedQwebExpressionsService;
        bottom_sheet: typeof bottomSheetService;
        command: typeof commandService;
        currency: typeof currencyService;
        datetime_picker: typeof datetimePickerService;
        demo_data: typeof demoDataService;
        density: typeof densityService;
        dialog: typeof dialogService;
        effect: typeof effectService;
        error: typeof errorService;
        field: typeof fieldService;
        file_upload: typeof fileUploadService;
        form_dialog_stack: typeof formDialogStackService;
        hotkey: typeof hotkeyService;
        http: typeof httpService;
        lazy_session: typeof lazySession;
        localization: typeof localizationService;
        menu: typeof menuService;
        multi_company_recovery: typeof multiCompanyRecoveryService;
        name: typeof nameService;
        notification: typeof notificationService;
        orm: typeof ormService;
        overlay: typeof overlayService;
        popover: typeof popoverService;
        profiling: typeof profilingService;
        "public.interactions": typeof publicInteractionService;
        pwa: typeof pwaService;
        reloadCompany: typeof reloadCompanyService;
        result_set_cache_invalidator: typeof resultSetCacheInvalidatorService;
        scss_error_display: typeof scssErrorNotificationService;
        shareTarget: typeof shareTargetService;
        slow_rpc: typeof slowRpcService;
        sortable: typeof sortableService;
        title: typeof titleService;
        tooltip: typeof tooltipService;
        tree_processor: typeof treeProcessorService;
        ui: typeof uiService;
        user_invite: typeof userInviteService;
        view: typeof viewService;
        "web.frequent.emoji": typeof frequentEmojiService;
        web_vitals: typeof webVitalsService;
    }
}
