/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";

class MediaSizeOptionPlugin extends Plugin {
    static id = "mediaSizeOption";
    /** @type {import("plugins").BuilderResources} */
    resources = {
        builder_actions: {
            MediaSizeSliderAction,
            MediaSizeTextAction,
            SetMediaSizeAutoAction,
        },
    };
}

/**
 * The width is a plain inline style, so it goes through the shared style
 * action rather than through a writer of our own.
 */
function setWidth(getAction, editingElement, value) {
    getAction("styleAction").apply({
        editingElement,
        params: { mainParam: "width" },
        value,
    });
}

export class MediaSizeSliderAction extends BuilderAction {
    static id = "mediaSizeSlider";
    static dependencies = ["builderActions"];
    getValue({ editingElement }) {
        // An unset width parks the slider at 99%, not 100%: from 100% a drag
        // to the right previews nothing, and the value would never commit.
        const width = editingElement.style.width;
        if (width === "auto" || width === "") {
            return "99%";
        }
        return width;
    }
    apply({ editingElement, value }) {
        setWidth(this.dependencies.builderActions.getAction, editingElement, value);
    }
}

export class MediaSizeTextAction extends BuilderAction {
    static id = "mediaSizeText";
    static dependencies = ["builderActions"];
    getValue({ editingElement }) {
        // Empty, so the input shows its "auto" placeholder instead of a number
        // the user never chose.
        const width = editingElement.style.width;
        return width === "auto" ? "" : width;
    }
    apply({ editingElement, value }) {
        setWidth(this.dependencies.builderActions.getAction, editingElement, value || "auto");
    }
}

export class SetMediaSizeAutoAction extends BuilderAction {
    static id = "setMediaSizeAuto";
    static dependencies = ["builderActions"];
    isApplied({ editingElement }) {
        const width = editingElement.style.width;
        return width === "auto" || width === "";
    }
    apply({ editingElement }) {
        setWidth(this.dependencies.builderActions.getAction, editingElement, "auto");
    }
    clean({ editingElement }) {
        setWidth(this.dependencies.builderActions.getAction, editingElement, "100%");
    }
}

registry.category("builder-plugins").add(MediaSizeOptionPlugin.id, MediaSizeOptionPlugin);
