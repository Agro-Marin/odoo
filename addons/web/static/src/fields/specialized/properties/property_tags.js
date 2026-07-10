// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/property_tags - Tag list component with color picker for property tag values */

import { Component } from "@odoo/owl";
import { AutoComplete } from "@web/components/autocomplete/autocomplete";
import { ColorList } from "@web/components/colorlist/colorlist";
import { useTagNavigation } from "@web/components/record_selectors/tag_navigation_hook";
import { TagsList } from "@web/components/tags_list/tags_list";
import { _t } from "@web/core/l10n/translation";
import { deepCopy } from "@web/core/utils/collections/objects";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
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
        selectedTags: {}, // Tags value visible in the tags list
        tags: {}, // Tags definition visible in the dropdown
        // Behavior of the tag delete button: "value" unselects the value,
        // "tags" removes it from the definition.
        deleteAction: { type: String },
        readonly: { type: Boolean, optional: true },
        canChangeTags: { type: Boolean, optional: true },
        // Select a new value
        onValueChange: { type: Function, optional: true },
        // Change the tags definition (may pass a 2nd arg to also update selection)
        onTagsChange: { type: Function, optional: true },
    };
    setup() {
        this.notification = useService("notification");
        this.popover = usePopover(
            /** @type {any} */ (this.constructor).components.Popover,
        );
        useTagNavigation("propertyTags", {
            delete: (index) => this.deleteTagByIndex(index),
        });
    }

    /* --------------------------------------------------------
     * Public methods / Getters
     * -------------------------------------------------------- */

    /**
     * Whether to display badges vs. just the tag label.
     * @returns {array}
     */
    get displayBadge() {
        return /** @type {any} */ (
            !this.env.config || this.env.config.viewType !== "kanban"
        );
    }

    /**
     * Tags values and actions for the TagsList component.
     * @returns {array}
     */
    get tagListItems() {
        if (!this.props.selectedTags || !this.props.selectedTags.length) {
            return [];
        }

        // Retrieve the tags label and color
        // ['a', 'b'] =>  [['a', 'A', 5], ['b', 'B', 6]]
        let value = this.props.tags.filter((tag) =>
            this.props.selectedTags.includes(tag[0]),
        );

        if (!this.displayBadge) {
            // in kanban view e.g. to not show tag without color
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
     * Current selected tags, deep-copied so callers can mutate/discard
     * without touching the original.
     * @returns {array}
     */
    get selectedTags() {
        return deepCopy(this.props.selectedTags || []);
    }

    /**
     * Current selectable tags, deep-copied so callers can mutate/discard
     * without touching the original.
     * @returns {array}
     */
    get availableTags() {
        return deepCopy(this.props.tags || []);
    }

    /**
     * Options available in the autocomplete component.
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
                        // no result, ask the user if he want to create a new tag
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

    /* --------------------------------------------------------
     * Event handlers
     * -------------------------------------------------------- */

    /**
     * Add one value to the current tag list values.
     * @param {string | object} tagValue Either {toCreate: true, value: label} to
     *      create a new value, or an existing value to select it.
     */
    onOptionSelected(tagValue) {
        const selectedTags = this.selectedTags;
        const newValue = [...selectedTags, tagValue];
        this.props.onValueChange(newValue);
    }

    /**
     * Create a new tag, add it to the definition, and select it.
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

        // cycle trough colors
        let tagColor =
            this.props.tags && this.props.tags.length
                ? (this.props.tags[this.props.tags.length - 1][2] + 1) %
                  ColorList.COLORS.length
                : Math.floor(Math.random() * ColorList.COLORS.length);
        tagColor = tagColor || 1; // never select white by default

        const newTag = [newValue, newLabel, tagColor];
        const updatedTags = [...this.availableTags, newTag];
        // automatically select the newly created tag
        const newValues = [...this.props.selectedTags, newTag[0]];
        this.props.onTagsChange(updatedTags, newValues);
    }

    /**
     * Delete-button handler for a tag pill; behavior depends on "deleteAction":
     * unselect the value, or remove it from the available tags.
     * @param {string} deleteTag ID of the tag to delete
     */
    onTagDelete(deleteTag) {
        if (this.props.deleteAction === "value") {
            // remove the tag from the value (but keep it in the options list)
            const selectedTags = this.selectedTags;
            const newValue = selectedTags.filter((tag) => tag !== deleteTag);
            this.props.onValueChange(newValue);
        } else {
            // remove the tag from the options
            const availableTags = this.availableTags;
            this.props.onTagsChange(
                availableTags.filter((tag) => tag[0] !== deleteTag),
            );
        }
    }

    /**
     * Click on a tag pill; open the color popover if the tag definition is editable.
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
     * Change the color of a tag.
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
     * Delete a tag by index (backspace navigation).
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

    get propertyTagsProps() {
        return {
            selectedTags: this.props.record.data[this.props.name] || [],
            tags: this.props.record.fields[this.props.name].tags || [],
            deleteAction: "value",
            readonly: this.props.readonly,
            canChangeTags: false,
            onValueChange: (value) => {
                this.props.record.update({ [this.props.name]: value });
            },
        };
    }
}

export const propertyTagsField = {
    component: PropertyTagsField,
};

registerField("property_tags", propertyTagsField);
