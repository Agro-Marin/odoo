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
    }

    /**
     * One entry of `fieldDependencies`. Mirrors FIELD_DEPENDENCIES_VALIDATION
     * in model/relational_model/field_metadata.js.
     *
     * These are FIELD descriptors, not widget descriptors. They used to be
     * typed as `Partial<StaticWidgetInfo>`, so every field key had to be bolted
     * onto the widget interface one at a time — `string` and `readonly` were,
     * and `written`, the key that decides whether the widget may edit the
     * field, was simply absent. week_days.js declares it on all seven of its
     * dependencies and was rejected for it.
     */
    interface FieldDependency {
        name: string;
        type?: string;
        optional?: boolean;
        readonly?: boolean | string;
        written?: boolean;
        string?: string;
        [key: string]: any;
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
            | FieldDependency[]
            | ((baseInfo: StaticWidgetInfo) => FieldDependency[]);
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
