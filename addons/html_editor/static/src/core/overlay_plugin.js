/** @odoo-module native */
import { EventBus, markRaw } from "@odoo/owl";

import { Plugin } from "../plugin.js";
import { EditorOverlay } from "./overlay.js";

/**
 * @typedef { Object } OverlayShared
 * @property { OverlayPlugin['createOverlay'] } createOverlay
 */

export class OverlayPlugin extends Plugin {
    static id = "overlay";
    static dependencies = ["history", "selection"];
    static shared = ["createOverlay"];

    overlays = [];

    setup() {
        this.targetRectProviders = this.getResource(
            "overlay_selection_target_rect_providers",
        );
    }

    destroy() {
        super.destroy();
        for (const overlay of this.overlays) {
            overlay.close();
        }
    }

    /**
     * @param {Function} Component
     * @param {Object} [props={}]
     * @param {Object} [options]
     * @returns {Overlay}
     */
    createOverlay(Component, props = {}, options) {
        const overlay = new Overlay(this, Component, props, options);
        this.overlays.push(overlay);
        return overlay;
    }

    getCustomRect() {
        for (const cb of this.targetRectProviders) {
            const rect = cb();
            if (rect) {
                return rect;
            }
        }
    }
}

export class Overlay {
    constructor(plugin, C, props, options) {
        this.plugin = plugin;
        this.C = C;
        this.editorOverlayProps = props;
        this.options = options;
        this.isOpen = false;
        this._remove = null;
        this.component = null;
        this.bus = new EventBus();
    }

    /**
     * @param {Object} options
     * @param {HTMLElement | null} [options.target]
     * @param {any} [options.props]
     */
    open({ target, props }) {
        if (this.isOpen) {
            this.updatePosition();
        } else {
            this.isOpen = true;
            const selection = this.plugin.editable.ownerDocument.getSelection();
            let initialSelection;
            if (selection && selection.type !== "None") {
                const rect = this.plugin.getCustomRect();
                initialSelection = {
                    range: selection.getRangeAt(0),
                    rect,
                };
            }
            this._remove = this.plugin.services.overlay.add(
                EditorOverlay,
                markRaw({
                    ...this.editorOverlayProps,
                    Component: this.C,
                    editable: this.plugin.editable,
                    props,
                    target,
                    initialSelection,
                    getCustomRect: this.plugin.getCustomRect.bind(this.plugin),
                    bus: this.bus,
                    close: this.close.bind(this),
                    isOverlayOpen: this.isOverlayOpen.bind(this),
                    shared: {
                        ignoreDOMMutations:
                            this.plugin.dependencies.history.ignoreDOMMutations,
                        getSelectionData:
                            this.plugin.dependencies.selection.getSelectionData,
                    },
                }),
                {
                    ...this.options,
                },
            );
        }
    }

    close() {
        this.isOpen = false;
        if (this._remove) {
            this._remove();
        }
    }

    isOverlayOpen() {
        return this.isOpen;
    }

    updatePosition() {
        this.bus.trigger("updatePosition");
    }
}
