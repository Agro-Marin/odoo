declare module "registries" {
    import { Component, ComponentConstructor } from "@odoo/owl";

    interface DynamicWidgetInfo {
        readonly: boolean;
    }

    interface StaticWidgetInfo {
        attrs: object;
        name: string;
        options: object;
        widget: ViewWidgetsRegistryItemShape;
        type?: string;
        // Carried by `fieldDependencies` entries, which are field descriptors
        // rather than widget descriptors — see week_days.js.
        string?: string;
        readonly?: boolean;
    }

    export interface ViewWidgetsRegistryItemShape {
        additionalClasses?: string[];
        component: ComponentConstructor;
        displayName?: string;
        extractProps?(
            options: Record<string, any>,
            dynamicInfo: DynamicWidgetInfo & Record<string, any>,
        ): Record<string, any>;
        fieldDependencies?:
            | Partial<StaticWidgetInfo>[]
            | ((baseInfo: StaticWidgetInfo) => Partial<StaticWidgetInfo>[]);
        supportedAttributes?: any[];
        supportedOptions?: any[];
        // Same escape hatch FieldsRegistryItemShape carries: widget entries take
        // arbitrary extra keys that consumers read dynamically.
        [key: string]: any;
    }

    interface GlobalRegistryCategories {
        view_widgets: ViewWidgetsRegistryItemShape;
    }
}
