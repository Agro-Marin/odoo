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

    export interface ViewWidgetsRegistryItemShape {
        additionalClasses?: string[];
        component: ComponentConstructor;
        extractProps?(options: object, dynamicInfo: DynamicWidgetInfo): object;
        fieldDependencies?: Partial<StaticWidgetInfo>[] | ((baseInfo: StaticWidgetInfo) => Partial<StaticWidgetInfo>[]);
    }

    interface GlobalRegistryCategories {
        view_widgets: ViewWidgetsRegistryItemShape;
    }
}
