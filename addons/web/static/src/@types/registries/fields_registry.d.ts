declare module "registries" {
    import { FieldDefinition, FieldType } from "fields";
    import { Component } from "@odoo/owl";
    import { Domain } from "@web/core/domain";
    import { _t } from "@web/core/translation";

    type TranslatableString = ReturnType<typeof _t> | string;

    interface DynamicFieldInfo {
        context: Record<string, any>;
        domain(): Domain | undefined;
        readonly: boolean;
    }

    interface StaticFieldInfo {
        attrs: Record<string, any>;
        context: string;
        decorations: Record<string, any>;
        domain?: string;
        field: FieldDefinition;
        forceSave: boolean;
        help?: TranslatableString;
        name: string;
        onChange: boolean;
        options: Record<string, any>;
        string: TranslatableString;
        type: string;
        viewType: string;
        widget?: string;
        readonly?: boolean;
        required?: boolean;
        invisible?: boolean | string;
    }

    /**
     * A field a widget needs loaded alongside the one it renders.
     *
     * NOT a `Partial<StaticFieldInfo>`, which is what this used to say: the
     * shape is the one `addFieldDependencies` consumes and
     * `FIELD_DEPENDENCIES_VALIDATION` enforces at runtime, and the two
     * disagreed. `optional` is the visible cost -- it is load-bearing (the
     * dependency becomes a no-op on a model that lacks the field) and read as a
     * misspelling of `options`.
     */
    interface FieldDependency extends Partial<StaticFieldInfo> {
        name: string;
        /** skip the dependency when the model has no such field */
        optional?: boolean;
        /** the widget writes it, which is what decides `readonly` */
        written?: boolean;
        readonly?: boolean | string;
        [key: string]: any;
    }

    type OptionType = "boolean" | "field" | "number" | "selection" | "string";

    interface IOption<T extends OptionType> {
        help?: TranslatableString;
        label: TranslatableString;
        name: string;
        type: T;
    }

    interface BooleanOption extends IOption<"boolean"> {
        default?: boolean;
    }

    interface FieldOption extends IOption<"field"> {
        availableTypes?: FieldType[];
    }

    interface NumberOption extends IOption<"number"> {
        default?: number;
    }

    interface StringOption extends IOption<"string"> {
        default?: string;
    }

    interface SelectionOptionChoice {
        label: TranslatableString;
        value: string;
    }

    interface SelectionOption extends IOption<"selection"> {
        choices: SelectionOptionChoice[];
        default?: string;
    }

    type SupportedOptions =
        BooleanOption | FieldOption | NumberOption | SelectionOption | StringOption;

    /**
     * What callers put on a field's info on top of StaticFieldInfo. Declared
     * (not folded into an index signature) because a destructuring parameter
     * requires the property to exist: `extractProps: ({ placeholder }) => ...`
     * is an error against a type that only has an index signature.
     */
    interface ExtraFieldInfo {
        placeholder?: string;
        displayPlaceholder?: boolean;
        optional?: string | boolean;
        relatedFields?: Record<string, any>;
        viewMode?: string;
        views?: Record<string, any>;
        value?: any;
        update?: (...args: any[]) => any;
        [key: string]: any;
    }

    export interface FieldsRegistryItemShape {
        additionalClasses?: string[];
        component: any;
        displayName?: TranslatableString;
        extractProps?(
            staticInfo: StaticFieldInfo & ExtraFieldInfo,
            dynamicInfo: DynamicFieldInfo & Record<string, any>,
        ): Record<string, any>;
        fieldDependencies?:
            FieldDependency[] | ((baseInfo: StaticFieldInfo) => FieldDependency[]);
        /**
         * `column_width_hook` is the only caller and hands it all three keys;
         * an implementation destructures the ones it reads. The return may be
         * undefined as well as false: the caller treats any falsy width as
         * "use the default for this type".
         */
        listViewWidth?:
            | number
            | number[]
            | ((param: {
                  type: string;
                  hasLabel: boolean;
                  options: Record<string, any>;
              }) => number | false | undefined);
        relatedFields?:
            | Partial<StaticFieldInfo>[]
            | ((baseInfo: StaticFieldInfo) => Partial<StaticFieldInfo>[]);
        isEmpty?(...args: any[]): boolean;
        supportedAttributes?: any[];
        supportedOptions?: any[];
        supportedTypes?: string[];
        useSubView?: boolean;
        [key: string]: any;
    }

    interface GlobalRegistryCategories {
        fields: FieldsRegistryItemShape;
    }
}
