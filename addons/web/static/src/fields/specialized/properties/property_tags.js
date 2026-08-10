// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/property_tags */

import { Component } from "@odoo/owl";
import { AutoComplete } from "@web/components/autocomplete/autocomplete";
import { ColorList } from "@web/components/colorlist/colorlist";
import { useTagNavigation } from "@web/components/record_selectors/tag_navigation_hook";
import { TagsList } from "@web/components/tags_list/tags_list";
import { _t } from "@web/core/translation";
import { deepCopy } from "@web/core/utils/collections/objects";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { usePopover } from "@web/ui/popover/popover_hook";

class PropertyTagsColorListPopover extends Component {
    static template = "web.PropertyTagsColorListPopover";
    static components = {
        ColorList,
    };
    static props = {
        colors: Array,
        tag: Object,
        switchTagColor: Function,
        close: Function,
    };
}

export class PropertyTags extends Component {
    static template = "web.PropertyTags";
    static components = {
        AutoComplete,
        TagsList,
        ColorList,
        Popover: PropertyTagsColorListPopover,
    };

    static props = {
        id: { type: String, optional: true },
        selectedTags: {},
        tags: {},
        deleteAction: { type: String },
        readonly: { type: Boolean, optional: true },
        canChangeTags: { type: Boolean, optional: true },
        onValueChange: { type: Function, optional: true },
        onTagsChange: { type: Function, optional: true },
    };
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {ReturnType<typeof usePopover>} */
    popover;

    setup() {
        this.notification = useService("notification");
        this.popover = usePopover(
            /** @type {any} */ (this.constructor).components.Popover,
        );
        useTagNavigation("propertyTags", {
            delete: (index) => this.deleteTagByIndex(index),
        });
    }

    /**
     * @returns {array}
     */
    get displayBadge() {
        return /** @type {any} */ (
            !this.env.config || this.env.config.viewType !== "kanban"
        );
    }

    /**
     * @returns {array}
     */
    get tagListItems() {
        if (!this.props.selectedTags || !this.props.selectedTags.length) {
            return [];
        }

        let value = this.props.tags.filter((tag) =>
            this.props.selectedTags.includes(tag[0]),
        );

        if (!this.displayBadge) {
            value = value.filter((tag) => tag[2]);
        }

        const canDeleteTag =
            !this.props.readonly &&
            (this.props.canChangeTags || this.props.deleteAction === "value");

        return value.map((tag) => {
            const [tagId, tagLabel, tagColorIndex] = tag;
            return {
                id: tagId,
                text: tagLabel,
                className: this.props.canChangeTags ? "" : "pe-none",
                colorIndex: tagColorIndex || 0,
                onClick: (event) => this.onTagClick(event, tagId, tagColorIndex),
                onDelete: canDeleteTag && (() => this.onTagDelete(tagId)),
            };
        });
    }

    /**
     * @returns {array}
     */
    get selectedTags() {
        return deepCopy(this.props.selectedTags || []);
    }

    /**
     * @returns {array}
     */
    get availableTags() {
        return deepCopy(this.props.tags || []);
    }

    /**
     * @returns {array}
     */
    get autocompleteSources() {
        return [
            {
                options: (request) => {
                    const tagsFiltered = this.props.tags.filter(
                        (tag) =>
                            (!this.props.selectedTags ||
                                !this.props.selectedTags.includes(tag[0])) &&
                            (!request ||
                                !request.length ||
                                tag[1]
                                    .toLocaleLowerCase()
                                    .includes(request.toLocaleLowerCase())),
                    );
                    if (!tagsFiltered || !tagsFiltered.length) {
                        if (!request || !request.length) {
                            return [
                                {
                                    label: _t("Start typing..."),
                                    cssClass: "fst-italic",
                                },
                            ];
                        } else if (!this.props.canChangeTags) {
                            return [
                                {
                                    label: _t("No result"),
                                    cssClass: "fst-italic",
                                },
                            ];
                        }

                        return [
                            {
                                label: _t('Create "%s"', request),
                                cssClass: "o_field_property_dropdown_add",
                                onSelect: () => this.onTagCreate(request),
                            },
                        ];
                    }
                    return tagsFiltered.map((tag) => ({
                        label: tag[1],
                        onSelect: () => this.onOptionSelected(tag[0]),
                    }));
                },
            },
        ];
    }

    /**
     * @param {string | object} tagValue
     */
    onOptionSelected(tagValue) {
        const selectedTags = this.selectedTags;
        const newValue = [...selectedTags, tagValue];
        this.props.onValueChange(newValue);
    }

    /**
     * @param {string} newLabel
     */
    async onTagCreate(newLabel) {
        if (!newLabel || !newLabel.length) {
            return;
        }

        const newValue = newLabel ? newLabel.toLowerCase().replace(/\s+/g, "_") : "";
        const existingTag = this.props.tags.find((tag) => tag[0] === newValue);

        if (existingTag) {
            this.notification.add(_t("This tag is already available"), {
                type: "warning",
            });
            return;
        }

        let tagColor =
            this.props.tags && this.props.tags.length
                ? (this.props.tags[this.props.tags.length - 1][2] + 1) %
                  ColorList.COLORS.length
                : Math.floor(Math.random() * ColorList.COLORS.length);
        tagColor = tagColor || 1;

        const newTag = [newValue, newLabel, tagColor];
        const updatedTags = [...this.availableTags, newTag];
        const newValues = [...this.props.selectedTags, newTag[0]];
        this.props.onTagsChange(updatedTags, newValues);
    }

    /**
     * @param {string} deleteTag
     */
    onTagDelete(deleteTag) {
        if (this.props.deleteAction === "value") {
            const selectedTags = this.selectedTags;
            const newValue = selectedTags.filter((tag) => tag !== deleteTag);
            this.props.onValueChange(newValue);
        } else {
            const availableTags = this.availableTags;
            this.props.onTagsChange(
                availableTags.filter((tag) => tag[0] !== deleteTag),
            );
        }
    }

    /**
     * @param {Event} event
     * @param {string} tagId
     * @param {integer} tagColor
     */
    onTagClick(event, tagId, tagColor) {
        if (!this.props.canChangeTags) {
            /** @type {HTMLElement} */ (event.currentTarget).blur();
            return;
        }
        this.popover.open(/** @type {HTMLElement} */ (event.currentTarget), {
            colors: [...Array(ColorList.COLORS.length).keys()],
            tag: { id: tagId, colorIndex: tagColor },
            switchTagColor: this.onTagColorSwitch.bind(this),
        });
    }

    /**
     * @param {integer} colorIndex
     * @param {object} currentTag
     */
    onTagColorSwitch(colorIndex, currentTag) {
        const availableTags = this.availableTags;
        availableTags.find((tag) => tag[0] === currentTag.id)[2] = colorIndex;
        this.props.onTagsChange(availableTags);

        this.popover.close();
    }

    /**
     * @param {integer} index
     */
    deleteTagByIndex(index) {
        this.onTagDelete(this.tagListItems[index].id);
    }
}

export class PropertyTagsField extends Component {
    static template = "web.PropertyTagsField";
    static components = { PropertyTags };
    static props = { ...standardFieldProps };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    get propertyTagsProps() {
        return {
            selectedTags: this.field.value || [],
            tags: this.field.definition.tags || [],
            deleteAction: "value",
            readonly: this.props.readonly,
            canChangeTags: false,
            onValueChange: (value) => {
                this.field.update(value);
            },
        };
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const propertyTagsField = {
    component: PropertyTagsField,
};

registerField("property_tags", propertyTagsField);
