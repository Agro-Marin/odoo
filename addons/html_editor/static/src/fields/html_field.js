/** @odoo-module native */
import { DYNAMIC_PLACEHOLDER_PLUGINS } from "@html_editor/backend/plugin_sets";
import { HtmlViewer } from "@html_editor/components/html_viewer/html_viewer";
import { EditorVersionPlugin } from "@html_editor/core/editor_version_plugin";
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { stripVersion } from "@html_editor/html_migrations/html_migrations_utils";
import { HtmlUpgradeManager } from "@html_editor/html_migrations/html_upgrade_manager";
import { stripHistoryIds } from "@html_editor/others/collaboration/collaboration_odoo_plugin";
import {
    MAIN_EMBEDDINGS,
    READONLY_MAIN_EMBEDDINGS,
} from "@html_editor/others/embedded_components/embedding_sets";
import {
    COLLABORATION_PLUGINS,
    EMBEDDED_COMPONENT_PLUGINS,
    MAIN_PLUGINS,
    NO_EMBEDDED_COMPONENTS_FALLBACK_PLUGINS,
} from "@html_editor/plugin_sets";
import { normalizeHTML } from "@html_editor/utils/html";
import { generateId } from "@html_editor/utils/ids";
import { withSequence } from "@html_editor/utils/resource";
import { fixInvalidHTML, instanceofMarkup } from "@html_editor/utils/sanitize";
import { Wysiwyg } from "@html_editor/wysiwyg";
import { Component, markup, status, useRef, useState } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Mutex } from "@web/core/utils/concurrency";
import { useBus, useService } from "@web/core/utils/hooks";
import { useFieldDirtySignal } from "@web/fields/field_dirty_signal";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { TranslationButton } from "@web/fields/translation_button";

const HTML_FIELD_METADATA_ATTRIBUTES = ["data-last-history-steps"];

/**
 * Check whether the given value contains nodes that would break
 * on insertion inside an existing body.
 *
 * @param {string} value
 * @returns {boolean} true if 'value' contains a node
 * that can only exist once per document.
 */
function computeContainsComplexHTML(value) {
    const domParser = new DOMParser();
    if (!value) {
        return false;
    }
    const parsedOriginal = domParser.parseFromString(value, "text/html");
    return !!parsedOriginal.head.innerHTML.trim();
}

export class HtmlField extends Component {
    static template = "html_editor.HtmlField";
    static props = {
        ...standardFieldProps,
        isCollaborative: { type: Boolean, optional: true },
        collaborativeTrigger: { type: String, optional: true },
        dynamicPlaceholder: { type: Boolean, optional: true, default: false },
        dynamicPlaceholderModelReferenceField: { type: String, optional: true },
        migrateHTML: { type: Boolean, optional: true },
        cssReadonlyAssetId: { type: String, optional: true },
        sandboxedPreview: { type: Boolean, optional: true },
        codeview: { type: Boolean, optional: true },
        editorConfig: { type: Object, optional: true },
        embeddedComponents: { type: Boolean, optional: true },
    };
    static defaultProps = {
        dynamicPlaceholder: false,
    };
    static components = {
        Wysiwyg,
        HtmlViewer,
        TranslationButton,
    };

    setup() {
        this.htmlUpgradeManager = new HtmlUpgradeManager();
        this.mutex = new Mutex();

        this.codeViewRef = useRef("codeView");

        const { model } = this.props.record;
        useBus(model.bus, ModelEvent.WILL_SAVE_URGENTLY, ({ detail }) =>
            // Push onto detail.proms so UrgentSaveCoordinator.run() awaits this
            // commit before the save reads _changes. Without it, the async commit
            // races the tab-close save, which then sees no changes and skips the
            // sendBeacon -- silently dropping the edit (and hanging tests that
            // await the beacon). Mirrors the NEED_LOCAL_CHANGES handler below.
            detail.proms.push(this.commitChanges({ urgent: true })),
        );
        useBus(model.bus, ModelEvent.NEED_LOCAL_CHANGES, ({ detail }) =>
            detail.proms.push(this.commitChanges()),
        );
        this.busService = this.env.services.bus_service;
        this.ormService = useService("orm");

        this.isDirty = false;
        // Owned dirty-signal emitter: this field's dirty state is tracked
        // under its own owner symbol (and cleared on destroy), so it cannot
        // clobber another field's announcement on the shared model bus.
        this.setFieldDirty = useFieldDirtySignal();
        // Monotonic counter bumped by every `onChange`. `_commitChanges` reads
        // it before awaiting the (async) content capture so it can tell whether
        // the user kept editing while the capture was in flight -- in which
        // case the captured content is stale and the field must stay dirty.
        this.changeSeq = 0;
        this.state = useState({
            key: 0,
            showCodeView: false,
            containsComplexHTML: computeContainsComplexHTML(
                this.props.record.data[this.props.name],
            ),
        });

        useRecordObserver((record) => {
            // Reset Wysiwyg when we discard or onchange value
            const newValue = fixInvalidHTML(record.data[this.props.name]);
            if (!this.isDirty) {
                const value = normalizeHTML(
                    newValue,
                    this.clearElementToCompare.bind(this),
                );
                if (this.lastValue !== value) {
                    this.state.key++;
                    this.state.containsComplexHTML =
                        computeContainsComplexHTML(newValue);
                    this.lastValue = value;
                }
            }
        });
        useRecordObserver((record) => {
            // update Dynamic Placeholder reference model
            if (this.props.dynamicPlaceholder && this.editor) {
                this.editor.shared.dynamicPlaceholder?.updateDphDefaultModel(
                    this.dynamicPlaceholderResModel(record),
                );
            }
        });
    }

    /**
     * Which model the placeholders in this field resolve against.
     *
     * `render_model` is the server's own answer, computed per model by
     * `mixin.mail.render._compute_render_model`; a view that names a field
     * explicitly still wins, because `sms.composer` is not a render mixin and
     * has no `render_model` to read.
     *
     * @param {Object} record
     * @returns {string | undefined}
     */
    dynamicPlaceholderResModel(record) {
        const named = this.props.dynamicPlaceholderModelReferenceField;
        return (
            (named && record.data[named]) ||
            record.data.render_model ||
            record.data.model
        );
    }

    get value() {
        const value = this.props.record.data[this.props.name] || "";
        let newVal = fixInvalidHTML(value);
        if (this.props.migrateHTML) {
            newVal = this.htmlUpgradeManager.processForUpgrade(newVal, {
                containsComplexHTML: this.state.containsComplexHTML,
                env: this.env,
            });
        }
        if (instanceofMarkup(value)) {
            return markup(newVal);
        }
        return newVal;
    }

    get displayReadonly() {
        return (
            this.props.readonly || (this.sandboxedPreview && !this.state.showCodeView)
        );
    }

    get wysiwygKey() {
        return `${this.props.record.resId}_${this.state.key}`;
    }

    get sandboxedPreview() {
        // @todo @phoenix maybe remove containsComplexHTML and alway use sandboxedPreview options
        return this.props.sandboxedPreview || this.state.containsComplexHTML;
    }

    get isTranslatable() {
        return this.props.record.fields[this.props.name].translate;
    }

    clearElementToCompare(element) {
        if (this.props.isCollaborative) {
            stripHistoryIds(element);
        }
        stripVersion(element);
    }

    /**
     * @param {string} value
     * @param {Object} [options]
     * @param {boolean} [options.isStale=false] when true, `value` was captured
     *        before a concurrent edit landed, so the field stays dirty and the
     *        newer content is committed by the next commit.
     */
    async updateValue(value, { isStale = false } = {}) {
        this.lastValue = normalizeHTML(value, this.clearElementToCompare.bind(this));
        this.isDirty = isStale;
        await this.props.record.update({ [this.props.name]: value }).catch(() => {
            this.isDirty = true;
        });
        this.setFieldDirty(this.isDirty);
    }

    async getEditorContent() {
        const content = this.editor.getElContent();
        const oldSrcToNewSrcMap =
            await this.editor.shared.imageSave?.savePendingImages(content);
        // Update the actual editable if still in the DOM.
        if (this.editor.editable && oldSrcToNewSrcMap) {
            this.editor.editable
                .querySelectorAll(".o_b64_image_to_save, .o_modified_image_to_save")
                .forEach((unsavedImage) => {
                    const oldSrc = unsavedImage.getAttribute("src");
                    if (oldSrcToNewSrcMap.has(oldSrc)) {
                        unsavedImage.setAttribute("src", oldSrcToNewSrcMap.get(oldSrc));
                    }
                    unsavedImage.classList.remove(
                        "o_b64_image_to_save",
                        "o_modified_image_to_save",
                    );
                });
        }
        return content;
    }

    async _commitChanges({ urgent }) {
        if (status(this) === "destroyed") {
            return;
        }
        if (this.state.showCodeView) {
            if (this.isDirty) {
                await this.updateValue(this.codeViewRef.el.value);
            }
            return;
        }
        if (urgent) {
            // Always persist the current editor content on an urgent (page-unload)
            // save -- do NOT gate on isDirty. A background image save (kicked off
            // below) updates the DOM to the finalized src without flipping
            // isDirty, and that finalized content still needs to be beaconed by
            // the next urgent save. record.update no-ops when nothing actually
            // changed, so committing while clean is harmless.
            await this.updateValue(this.editor.getContent());
            // Finish pending image uploads in the background: sendBeacon can't
            // await the upload round-trip during unload. A subsequent save
            // beacons the finalized src once the round-trip completes.
            this.getEditorContent();
            return;
        }
        if (this.isDirty) {
            // `getEditorContent` awaits pending image uploads; the user can keep
            // typing during that round-trip. Capture the change counter first so
            // a concurrent edit does not get marked clean (and silently dropped)
            // by the `updateValue` below, which only carries the stale snapshot.
            const seqAtCapture = this.changeSeq;
            const el = await this.getEditorContent();
            const content = el.innerHTML;
            this.clearElementToCompare(el);
            await this.updateValue(content, {
                isStale: this.changeSeq !== seqAtCapture,
            });
        }
    }

    async commitChanges({ urgent } = {}) {
        if (urgent) {
            return this._commitChanges({ urgent });
        } else {
            return this.mutex.exec(() => this._commitChanges({ urgent }));
        }
    }

    onEditorLoad(editor) {
        this.editor = editor;
    }

    onChange() {
        this.isDirty = true;
        this.changeSeq++;
        this.setFieldDirty(true);
    }

    onBlur() {
        return this.commitChanges();
    }

    async toggleCodeView() {
        await this.commitChanges();
        this.state.showCodeView = !this.state.showCodeView;
        if (!this.state.showCodeView && this.editor) {
            this.editor.editable.innerHTML = this.value;
            this.editor.shared.history.addStep();
        }
    }

    getConfig() {
        const config = {
            content: this.value,
            Plugins: [
                ...(this.props.migrateHTML ? [EditorVersionPlugin] : []),
                ...MAIN_PLUGINS,
                ...(this.props.isCollaborative ? COLLABORATION_PLUGINS : []),
                ...(this.props.dynamicPlaceholder ? DYNAMIC_PLACEHOLDER_PLUGINS : []),
                ...(this.props.embeddedComponents
                    ? EMBEDDED_COMPONENT_PLUGINS
                    : NO_EMBEDDED_COMPONENTS_FALLBACK_PLUGINS),
            ],
            classList: this.classList,
            onChange: this.onChange.bind(this),
            collaboration: this.props.isCollaborative && {
                busService: this.busService,
                ormService: this.ormService,
                collaborativeTrigger: this.props.collaborativeTrigger,
                collaborationChannel: {
                    collaborationModelName: this.props.record.resModel,
                    collaborationFieldName: this.props.name,
                    collaborationResId: parseInt(this.props.record.resId),
                },
                peerId: this.generateId(),
            },
            dropImageAsAttachment: true, // @todo @phoenix always true ?
            dynamicPlaceholder: this.props.dynamicPlaceholder,
            dynamicPlaceholderResModel: this.dynamicPlaceholderResModel(
                this.props.record,
            ),
            direction: localization.direction || "ltr",
            getRecordInfo: () => {
                const { resModel, resId, data, fields, id } = this.props.record;
                return { resModel, resId, data, fields, id };
            },
            resources: {},
            ...this.props.editorConfig,
        };

        if (!("baseContainers" in config)) {
            config.baseContainers = ["DIV", "P"];
        }

        if (this.props.embeddedComponents) {
            config.resources.embedded_components = [...MAIN_EMBEDDINGS];
            config.embeddedComponentInfo = { app: this.__owl__.app, env: this.env };
        }

        const { sanitize_tags, sanitize } = this.props.record.fields[this.props.name];
        if (
            !("allowVideo" in config) &&
            !this.props.embeddedComponents &&
            (sanitize_tags || (sanitize_tags === undefined && sanitize))
        ) {
            config.allowVideo = false; // Tag-sanitized fields remove videos.
        }
        if (this.props.codeview) {
            config.resources = {
                ...config.resources,
                user_commands: [
                    {
                        id: "codeview",
                        description: _t("Code view"),
                        icon: "fa-code",
                        run: this.toggleCodeView.bind(this),
                        isAvailable: isHtmlContentSupported,
                    },
                ],
                toolbar_groups: withSequence(100, {
                    id: "codeview",
                }),
                toolbar_items: {
                    id: "codeview",
                    groupId: "codeview",
                    commandId: "codeview",
                },
            };
        }
        return config;
    }

    getReadonlyConfig() {
        const config = {
            value: this.value,
            cssAssetId: this.props.cssReadonlyAssetId,
            hasFullHtml: this.sandboxedPreview,
        };
        if (this.props.embeddedComponents) {
            config.embeddedComponents = [...READONLY_MAIN_EMBEDDINGS];
        }
        return config;
    }

    generateId() {
        return generateId();
    }
}

export const htmlField = {
    component: HtmlField,
    displayName: _t("Html"),
    supportedTypes: ["html"],
    // `codeview` is declared but never appears in the registry-contract test's
    // drift report: `extractProps` reads it as `odoo.debug && options.codeview`,
    // and with debug off the `&&` short-circuits before the option is touched.
    // It is a real option either way, so it belongs here.
    supportedOptions: [
        {
            label: _t("Height"),
            name: "height",
            type: "number",
            help: _t("Fixed editor height in pixels; the content scrolls past it."),
        },
        {
            label: _t("Allow images"),
            name: "allowImage",
            type: "boolean",
        },
        {
            label: _t("Allow documents"),
            name: "allowMediaDocuments",
            type: "boolean",
        },
        {
            label: _t("Allow videos"),
            name: "allowVideo",
            type: "boolean",
        },
        {
            label: _t("Allow files"),
            name: "allowFile",
            type: "boolean",
        },
        {
            label: _t("Allow checklists"),
            name: "allowChecklist",
            type: "boolean",
        },
        {
            label: _t("Allow attachment creation"),
            name: "allowAttachmentCreation",
            type: "boolean",
            help: _t("Sets both image and file permissions at once."),
        },
        {
            label: _t("Base containers"),
            name: "baseContainers",
            type: "string",
            help: _t("Tag names the editor may use to wrap a block of content."),
        },
        {
            label: _t("Clean empty structural containers"),
            name: "cleanEmptyStructuralContainers",
            type: "boolean",
        },
        {
            label: _t("Debounce hints"),
            name: "debounceHints",
            type: "boolean",
        },
        {
            label: _t("Debounce power buttons"),
            name: "debouncePowerbuttons",
            type: "boolean",
        },
        {
            label: _t("Collaborative"),
            name: "collaborative",
            type: "boolean",
            help: _t("Share one editing session between everyone on the record."),
        },
        {
            label: _t("Collaborative trigger"),
            name: "collaborative_trigger",
            type: "string",
            help: _t("What opens the shared session: 'start' or 'focus'."),
        },
        {
            label: _t("Migrate HTML"),
            name: "migrateHTML",
            type: "boolean",
            help: _t("Run stored content through the upgrade pass. On by default."),
        },
        {
            label: _t("Dynamic Placeholder"),
            name: "dynamic_placeholder",
            type: "boolean",
            help: _t(
                "Offer a picker that inserts a {{object.field}} expression into the text.",
            ),
        },
        {
            label: _t("Dynamic Placeholder model reference"),
            name: "dynamic_placeholder_model_reference_field",
            type: "field",
            availableTypes: ["char"],
            help: _t("Field holding the model name whose fields the picker offers."),
        },
        {
            label: _t("Embedded components"),
            name: "embedded_components",
            type: "boolean",
            help: _t("Allow embedded components in the content. On by default."),
        },
        {
            label: _t("Sandboxed preview"),
            name: "sandboxedPreview",
            type: "boolean",
            help: _t("Render the content in a sandboxed iframe instead of editing it."),
        },
        {
            label: _t("Readonly stylesheet"),
            name: "cssReadonly",
            type: "string",
            help: _t("Asset bundle id to style the readonly rendering with."),
        },
        {
            label: _t("Code view"),
            name: "codeview",
            type: "boolean",
            help: _t("Offer a raw-HTML editing toggle. Debug mode only."),
        },
    ],
    // See `HtmlField.dynamicPlaceholderResModel`: the picker reads the model out
    // of `record.data`, and `render_model` is the server's own answer, so no
    // view needs to name it. Both are `optional` -- a model with neither simply
    // drops them from the read.
    fieldDependencies({ options }) {
        return options?.dynamic_placeholder
            ? [
                  { name: "render_model", optional: true, readonly: true },
                  { name: "model", optional: true, readonly: true },
              ]
            : [];
    },
    extractProps({ attrs, options }, dynamicInfo) {
        const editorConfig = {
            mediaModalParams: {
                useMediaLibrary: true,
            },
        };
        if (attrs.placeholder) {
            editorConfig.placeholder = attrs.placeholder;
        }
        if (options.height) {
            editorConfig.height = `${options.height}px`;
            editorConfig.classList = ["overflow-auto"];
        }
        if ("allowImage" in options) {
            editorConfig.allowImage = Boolean(options.allowImage);
        }
        if ("allowMediaDocuments" in options) {
            editorConfig.allowMediaDocuments = Boolean(options.allowMediaDocuments);
        }
        if ("allowVideo" in options) {
            editorConfig.allowVideo = Boolean(options.allowVideo);
        }
        if ("allowFile" in options) {
            editorConfig.allowFile = Boolean(options.allowFile);
        }
        if ("allowChecklist" in options) {
            editorConfig.allowChecklist = Boolean(options.allowChecklist);
        }
        if ("allowAttachmentCreation" in options) {
            editorConfig.allowImage = Boolean(options.allowAttachmentCreation);
            editorConfig.allowFile = Boolean(options.allowAttachmentCreation);
        }
        if ("baseContainers" in options) {
            editorConfig.baseContainers = options.baseContainers;
        }
        if ("cleanEmptyStructuralContainers" in options) {
            editorConfig.cleanEmptyStructuralContainers = Boolean(
                options.cleanEmptyStructuralContainers,
            );
        }
        if ("debounceHints" in options) {
            editorConfig.debounceHints = Boolean(options.debounceHints);
        }
        if ("debouncePowerbuttons" in options) {
            editorConfig.debouncePowerbuttons = Boolean(options.debouncePowerbuttons);
        }
        return {
            editorConfig,
            isCollaborative: options.collaborative,
            collaborativeTrigger: options.collaborative_trigger,
            migrateHTML: "migrateHTML" in options ? Boolean(options.migrateHTML) : true,
            dynamicPlaceholder: options.dynamic_placeholder,
            dynamicPlaceholderModelReferenceField:
                options.dynamic_placeholder_model_reference_field,
            embeddedComponents:
                "embedded_components" in options
                    ? Boolean(options.embedded_components)
                    : true,
            sandboxedPreview: Boolean(options.sandboxedPreview),
            cssReadonlyAssetId: options.cssReadonly,
            codeview: Boolean(odoo.debug && options.codeview),
        };
    },
};

registry.category("fields").add("html", htmlField, { force: true });

export function getHtmlFieldMetadata(content) {
    const metadata = {};
    for (const attribute of HTML_FIELD_METADATA_ATTRIBUTES) {
        const regex = new RegExp(`${attribute}\\s*=\\s*"([^"]+)"`);
        metadata[attribute] = content.match(regex)?.[1];
    }
    return metadata;
}
export function setHtmlFieldMetadata(content, metadata) {
    const htmlContent = content.toString() || "<div></div>";
    const parser = new DOMParser();
    const contentDocument = parser.parseFromString(htmlContent, "text/html");
    for (const [attribute, value] of Object.entries(metadata)) {
        if (value) {
            contentDocument.body.firstChild.setAttribute(attribute, value);
        }
    }
    return contentDocument.body.innerHTML;
}
