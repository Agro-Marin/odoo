declare module "registries" {
    import { Component, ComponentConstructor } from "@odoo/owl";
    import { OdooEnv } from "@web/env";
    import { NotificationOptions } from "@web/ui/notification/notification_service";
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

    // `remove` is the fallback branch: with effects switched off, `rainbow_man`
    // opens a notification instead and hands back its dismisser, so `effect.add`
    // returns a handle whichever branch ran.
    export type EffectsRegistryItemShape = (env: OdooEnv, params: object) => ({ Component?: ComponentConstructor, props?: object, remove?: () => void } | undefined);

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

    export type SerializersRegistryItemShape = (value: any) => any;
    export type DeserializersRegistryItemShape = (value: any, field?: any) => any;

    export type PublicComponentsRegistryItemShape = ComponentConstructor;

    export type SampleServerRegistryItemShape = (...args: any[]) => any;

    export interface SystrayRegistryItemShape {
        Component: ComponentConstructor;
        props?: Record<string, any>;
        isDisplayed?: (env: OdooEnv) => boolean;
    }

    export type IrActionsReportHandlers = (action: ActionRequest, options: ActionOptions, env: OdooEnv) => (void | boolean | Promise<void | boolean>);

    export type InteractionRegistryItemShape = typeof Interaction;

    export interface ColorPickerTabsRegistryItemShape {
        id: string;
        name: string;
        component: ComponentConstructor;
    }

    export interface DebugSectionRegistryItemShape {
        label: string;
        sequence?: number;
    }

    export type SharedComponentsRegistryItemShape = Function;

    export type UserMenuItemsRegistryItemShape = (env: OdooEnv) => {
        type: string;
        id?: string;
        description?: string;
        callback?: () => any;
        href?: string;
        sequence?: number;
        /** Read by UserMenu's filter; spreading the item drops the index signature. */
        hide?: boolean;
        show?: () => boolean;
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
        serializers: SerializersRegistryItemShape;
        deserializers: DeserializersRegistryItemShape;
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
