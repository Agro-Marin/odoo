import { ImageField, imageField } from "@web/fields/media/image/image_field";
import { registry } from "@web/core/registry";

export class ResourceAvatarField extends ImageField {
    static template = "resource.ResourceAvatarField";

    get isUserResource() {
        return this.props.record.data.resource_type === "user";
    }

    get backgroundClass() {
        return `o_colorlist_item_color_${this.props.record.data.color}`;
    }
}

registry.category("fields").add("resource_avatar", {
    ...imageField, // includes extractProps, supportedOptions, etc.
    component: ResourceAvatarField,
    fieldDependencies: [
        ...imageField.fieldDependencies,
        { name: "color", type: "integer" },
        { name: "resource_type", type: "selection" },
    ],
});
