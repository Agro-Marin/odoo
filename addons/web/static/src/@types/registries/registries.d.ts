declare module "registries" {
    import { Component, ComponentConstructor } from "@odoo/owl";
    import { OdooEnv } from "@web/env";
    import { NotificationOptions } from "@web/services/notifications/notification_service";
    import { Interaction } from "@web/public/interaction";
    import { Compiler } from "@web/views/view_compiler";
    import { ActionDescription } from "@web/webclient/actions/action_service";

    interface ActionHandlerParams {
        action: object;
        env: OdooEnv;
        options: ActionOptions;
    }
    export type ActionHandlersRegistryItemShape = (params: ActionHandlerParams) => (void | Promise<void>);

    export type ActionsRegistryItemShape = (((env: OdooEnv, action: ActionDescription) => void) | ComponentConstructor) & {
        displayName?: string;
        path?: string;
        target?: ActionMode;
    };

    export interface CogMenuRegistryItemShape {
        Component: ComponentConstructor;
        groupNumber: number;
        isDisplayed?: (env: OdooEnv) => boolean;
    }

    export type DialogsRegistryItemShape = ComponentConstructor;

    export type EffectsRegistryItemShape = (env: OdooEnv, params: object) => ({ Component: ComponentConstructor, props: object } | undefined);

    export type ErrorDialogsRegistryItemShape = ComponentConstructor;

    export type ErrorHandlersRegistryItemShape = (env: OdooEnv, error: any, originalError?: any) => boolean | void;

    export type ErrorNotificationsRegistryItemShape = NotificationOptions & { message?: string };

    export interface FavoriteMenuRegistryItemShape {
        Component: ComponentConstructor;
        groupNumber: number;
        isDisplayed?: (env: OdooEnv) => boolean;
    }

    export type FormattersRegistryItemShape = (value: any, options?: any) => any;

    export type FormCompilersRegistryItemShape = Compiler;

    interface KanbanHeaderConfigItemsFnParams {
        permissions: {
            canArchiveGroup: boolean;
            canDeleteGroup: boolean;
            canEditGroup: boolean;
        };
        props: object;
    }
    export interface GroupConfigItemsRegistryItemShape {
        label: String;
        method: string | (() => {});
        isVisible: boolean | ((params: KanbanHeaderConfigItemsFnParams) => boolean);
        class: string | ((params: KanbanHeaderConfigItemsFnParams) => (string | string[] | { [key: string]: boolean }));
        icon?: string;
        [key: string]: any;
    }

    export type LazyComponentsRegistryItemShape = ComponentConstructor;

    export interface MainComponentsRegistryItemShape {
        Component: ComponentConstructor;
        props?: object;
    }

    export type ParsersRegistryItemShape = (value: any, options?: any) => any;

    export type PublicComponentsRegistryItemShape = ComponentConstructor;

    export type SampleServerRegistryItemShape = (...args: any[]) => any;

    export interface SystrayRegistryItemShape {
        Component: ComponentConstructor;
        isDisplayed?: (env: OdooEnv) => boolean;
    }

    export type IrActionsReportHandlers = (action: ActionRequest, options: ActionOptions, env: OdooEnv) => (void | boolean | Promise<void | boolean>);

    export type InteractionRegistryItemShape = typeof Interaction;

    // Color picker tab. `id` matches against `props.enabledTabs` on the
    // ColorPicker component; `component` is rendered when the tab is active.
    // Runtime schema lives at `components/color_picker/color_picker.js`.
    export interface ColorPickerTabsRegistryItemShape {
        id: string;
        name: string;
        component: ComponentConstructor;
    }

    // Debug menu section header. Sections group debug-menu items;
    // `sequence` orders the section blocks vertically (default 50 if absent).
    // Runtime schema lives at `services/debug/debug_menu_basic.js`.
    export interface DebugSectionRegistryItemShape {
        label: string;
        sequence?: number;
    }

    // Bag of utility helpers / component classes shared across view layers
    // via registry indirection to break import cycles. Entries are
    // typeof-function (covers both utility functions and Component classes,
    // since class declarations are functions). Runtime schema is the
    // predicate `(entry) => typeof entry === "function"` at
    // `views/form/form_utils.js`. Callers read entries with `.get(key)` and
    // invoke as-appropriate for the key.
    export type SharedComponentsRegistryItemShape = Function;

    // Factory function for an entry in the user menu (top-right systray
    // dropdown). Invoked with the env and returns the item descriptor.
    // The `type` field discriminates "item" (clickable / link) from
    // "separator" and similar. Runtime schema is the predicate
    // `(entry) => typeof entry === "function"` at
    // `webclient/user_menu/user_menu.js`. The returned object's full shape
    // is consumer-defined (`webclient/user_menu/user_menu_items.js`) — the
    // catch-all index signature allows additional fields like `show`,
    // `hide`, `isDisplayed`, etc., without forcing every factory to declare
    // them.
    export type UserMenuItemsRegistryItemShape = (env: OdooEnv) => {
        type: string;
        id?: string;
        description?: string;
        callback?: () => any;
        href?: string;
        sequence?: number;
        [key: string]: any;
    };

    interface GlobalRegistryCategories {
        action_handlers: ActionHandlersRegistryItemShape;
        actions: ActionsRegistryItemShape;
        cogMenu: CogMenuRegistryItemShape;
        color_picker_tabs: ColorPickerTabsRegistryItemShape;
        debug_section: DebugSectionRegistryItemShape;
        dialogs: DialogsRegistryItemShape;
        effects: EffectsRegistryItemShape;
        error_dialogs: ErrorDialogsRegistryItemShape;
        error_handlers: ErrorHandlersRegistryItemShape;
        error_notifications: ErrorNotificationsRegistryItemShape;
        favoriteMenu: FavoriteMenuRegistryItemShape;
        formatters: FormattersRegistryItemShape;
        form_compilers: FormCompilersRegistryItemShape;
        group_config_items: GroupConfigItemsRegistryItemShape;
        lazy_components: LazyComponentsRegistryItemShape;
        main_components: MainComponentsRegistryItemShape;
        parsers: ParsersRegistryItemShape;
        public_components: PublicComponentsRegistryItemShape;
        "public.interactions": InteractionRegistryItemShape;
        sample_server: SampleServerRegistryItemShape;
        shared_components: SharedComponentsRegistryItemShape;
        systray: SystrayRegistryItemShape;
        user_menuitems: UserMenuItemsRegistryItemShape;
        "ir.actions.report handlers": IrActionsReportHandlers;
        /** Catch-all for dynamically registered categories */
        [key: string]: any;
    }
}
