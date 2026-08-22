/** @odoo-module native */
import { nodeToTree } from "@html_editor/core/history_plugin";
import { Plugin } from "@html_editor/plugin";
import { selectElements } from "@html_editor/utils/dom_traversal";
import { withSequence } from "@html_editor/utils/resource";
import { memoize } from "@web/core/utils/functions";
import { renderToElement } from "@web/core/utils/render";

/**
 * @typedef { Object } EmbeddedComponentShared
 * @property { EmbeddedComponentPlugin['renderBlueprintToElement'] } renderBlueprintToElement
 */

/**
 * @typedef {((arg: { name, env, props }) => void)[]} mount_component_handlers
 * @typedef {(() => void)[]} post_mount_component_handlers
 */

export class EmbeddedComponentPlugin extends Plugin {
    static id = "embeddedComponents";
    static dependencies = ["history", "protectedNode", "selection"];
    static shared = ["renderBlueprintToElement"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        normalize_handlers: withSequence(0, this.normalize.bind(this)),
        clean_for_save_handlers: ({ root }) => this.cleanForSave(root),
        attribute_change_handlers: this.onChangeAttribute.bind(this),
        restore_savepoint_handlers: () => this.handleComponents(this.editable),
        history_reset_handlers: () => this.handleComponents(this.editable),
        history_reset_from_steps_handlers: () => this.handleComponents(this.editable),
        step_added_handlers: ({ stepCommonAncestor }) =>
            this.handleComponents(stepCommonAncestor),
        external_step_added_handlers: () => this.handleComponents(this.editable),

        before_sanitize_processors: this.preProcessSanitizedElem.bind(this),
        after_sanitize_processors: this.postProcessSanitizedElem.bind(this),
        serializable_descendants_processors:
            this.processDescendantsToSerialize.bind(this),
        attribute_change_processors: this.onChangeAttribute.bind(this),
        savable_mutation_record_predicates: this.isMutationRecordSavable.bind(this),
        move_node_whitelist_selectors: "[data-embedded]",
    };

    setup() {
        this.components = new Set();
        this.nodeMap = new WeakMap();
        this.app = this.config.embeddedComponentInfo.app;
        this.env = this.config.embeddedComponentInfo.env ?? {};
        this.hostToStateChangeManagerMap = new WeakMap();
        this.hostToOnComponentInsertedMap = new WeakMap();
        this.embeddedComponents = memoize((embeddedComponents = []) => {
            const result = {};
            for (const embedding of embeddedComponents) {
                result[embedding.name] = embedding;
            }
            return result;
        });
    }

    isMutationRecordSavable(record) {
        const info = this.nodeMap.get(record.target);
        if (
            info &&
            record.type === "attributes" &&
            record.attributeName === "data-embedded-props"
        ) {
            return false;
        }
        return true;
    }

    /**
     * @typedef {import("@html_editor/core/history_plugin").Tree} Tree
     * @param {Node} elem
     * @param {Tree[]} serializableDescendants
     * @returns {Tree[]}
     */
    processDescendantsToSerialize(elem, serializableDescendants) {
        const embedding = this.getEmbedding(elem);
        if (!embedding) {
            return serializableDescendants;
        }
        return Object.values(embedding.getEditableDescendants?.(elem) || {}).map(
            nodeToTree,
        );
    }

    handleComponents(elem) {
        this.destroyRemovedComponents([...this.components]);
        this.forEachEmbeddedComponentHost(elem, (host, embedding) => {
            const info = this.nodeMap.get(host);
            if (!info) {
                this.mountComponent(host, embedding);
            }
        });
    }

    forEachEmbeddedComponentHost(elem, callback) {
        const selector = `[data-embedded]`;
        const targets = [...elem.querySelectorAll(selector)];
        if (elem.matches(selector)) {
            targets.unshift(elem);
        }
        for (const host of targets) {
            const embedding = this.getEmbedding(host);
            if (!embedding) {
                continue;
            }
            callback(host, embedding);
        }
    }

    getEmbedding(host) {
        return this.embeddedComponents(this.getResource("embedded_components"))[
            host.dataset.embedded
        ];
    }

    /**
     * @param {Object} attributeChange
     * @param { Object } options
     * @param { boolean } options.forNewStep
     * @returns {string}
     */
    onChangeAttribute(attributeChange, { forNewStep = false } = {}) {
        const attributeValue = attributeChange.value;
        let newAttributeValue;
        if (attributeChange.attributeName === "data-embedded-state") {
            const attrState = attributeChange.reverse
                ? attributeChange.oldValue
                : attributeChange.value;
            const stateChangeManager = this.getStateChangeManager(
                attributeChange.target,
            );
            if (stateChangeManager) {
                newAttributeValue = stateChangeManager.onStateChanged(attrState, {
                    reverse: attributeChange.reverse,
                    forNewStep,
                });
            }
        }
        return newAttributeValue || attributeValue;
    }

    getStateChangeManager(host) {
        const embedding = this.getEmbedding(host);
        if (!("getStateChangeManager" in embedding)) {
            return null;
        }
        if (!this.hostToStateChangeManagerMap.has(host)) {
            const config = {
                host,
                commitStateChanges: () => this.dependencies.history.addStep(),
            };
            const stateChangeManager = embedding.getStateChangeManager(config);
            stateChangeManager.setup();
            this.hostToStateChangeManagerMap.set(host, stateChangeManager);
        }
        return this.hostToStateChangeManagerMap.get(host);
    }

    mountComponent(
        host,
        { Component, getEditableDescendants, getProps, name, getStateChangeManager },
    ) {
        const props = getProps?.(host) || {};
        const env = Object.create(this.env);
        env.editorShared = {};
        if (getStateChangeManager) {
            env.getStateChangeManager = this.getStateChangeManager.bind(this);
        }
        if (getEditableDescendants) {
            env.getEditableDescendants = getEditableDescendants;
            Object.assign(env.editorShared, {
                selection: { ...this.dependencies.selection },
            });
        }
        this.dispatchTo("mount_component_handlers", { name, env, props });
        const root = this.app.createRoot(Component, {
            props,
            env,
        });
        root.mount(host);
        const fiber = root.node.fiber;
        const fiberComplete = fiber.complete;
        fiber.complete = () => {
            host.replaceChildren();
            fiberComplete.call(fiber);
            this.dispatchTo("post_mount_component_handlers");
        };
        const onComponentInserted = this.extractOnComponentInserted(host);
        if (onComponentInserted) {
            root.node.mounted.push(onComponentInserted);
        }
        const info = {
            root,
            host,
        };
        this.components.add(info);
        this.nodeMap.set(host, info);
    }

    destroyRemovedComponents(infos) {
        this.dependencies.history.ignoreDOMMutations(() => {
            for (const info of infos) {
                if (!this.editable.contains(info.host)) {
                    const host = info.host;
                    const display = host.style.display;
                    const parentNode = host.parentNode;
                    const clone = host.cloneNode(false);
                    if (parentNode) {
                        parentNode.replaceChild(clone, host);
                    }
                    host.style.display = "none";
                    this.editable.after(host);
                    this.destroyComponent(info);
                    if (parentNode) {
                        parentNode.replaceChild(host, clone);
                    } else {
                        host.remove();
                    }
                    host.style.display = display;
                    if (!host.getAttribute("style")) {
                        host.removeAttribute("style");
                    }
                }
            }
        });
    }

    deepDestroyComponent({ host }) {
        const removed = [];
        this.forEachEmbeddedComponentHost(host, (containedHost) => {
            const info = this.nodeMap.get(containedHost);
            if (info) {
                if (this.editable.contains(containedHost)) {
                    this.destroyComponent(info);
                } else {
                    removed.push(info);
                }
            }
        });
        this.destroyRemovedComponents(removed);
    }

    destroyComponent({ root, host }) {
        const { getEditableDescendants } = this.getEmbedding(host);
        const editableDescendants = getEditableDescendants?.(host) || {};
        root.destroy();
        this.components.delete(arguments[0]);
        this.nodeMap.delete(host);
        host.append(...Object.values(editableDescendants));
    }

    destroy() {
        super.destroy();
        for (const info of [...this.components]) {
            if (this.components.has(info)) {
                this.deepDestroyComponent(info);
            }
        }
    }

    /**
     * @param {String} template
     * @param {Object} [context]
     * @param {Function} [onComponentInserted]
     * @returns {HTMLElement}
     */
    renderBlueprintToElement(template, context = {}, onComponentInserted = undefined) {
        const host = renderToElement(template, context);
        if (onComponentInserted) {
            this.hostToOnComponentInsertedMap.set(host, onComponentInserted);
        }
        return host;
    }

    extractOnComponentInserted(host) {
        const onComponentInserted = this.hostToOnComponentInsertedMap.get(host);
        this.hostToOnComponentInsertedMap.delete(host);
        return onComponentInserted;
    }

    normalize(elem) {
        this.forEachEmbeddedComponentHost(elem, (host, { getEditableDescendants }) => {
            this.dependencies.protectedNode.setProtectingNode(host, true);
            const editableDescendants = getEditableDescendants?.(host) || {};
            for (const editableDescendant of Object.values(editableDescendants)) {
                this.dependencies.protectedNode.setProtectingNode(
                    editableDescendant,
                    false,
                );
            }
        });
    }

    cleanForSave(clone) {
        this.forEachEmbeddedComponentHost(clone, (host, { getEditableDescendants }) => {
            const editableDescendants = getEditableDescendants?.(host) || {};
            host.replaceChildren();
            for (const editableDescendant of Object.values(editableDescendants)) {
                delete editableDescendant.dataset.oeProtected;
                host.append(editableDescendant);
            }
            delete host.dataset.oeProtected;
            delete host.dataset.embeddedState;
        });
    }

    preProcessSanitizedElem(elem) {
        if (elem?.nodeType !== Node.ELEMENT_NODE) {
            return elem;
        }
        for (const host of selectElements(
            elem,
            "[data-embedded-props], [data-embedded-state]",
        )) {
            if (host.dataset.embeddedProps) {
                host.dataset.embeddedProps = encodeURIComponent(
                    host.dataset.embeddedProps,
                );
            }
            if (host.dataset.embeddedState) {
                host.dataset.embeddedState = encodeURIComponent(
                    host.dataset.embeddedState,
                );
            }
        }
        return elem;
    }

    postProcessSanitizedElem(elem) {
        if (elem?.nodeType !== Node.ELEMENT_NODE) {
            return elem;
        }
        for (const host of selectElements(
            elem,
            "[data-embedded-props], [data-embedded-state]",
        )) {
            if (host.dataset.embeddedProps) {
                host.dataset.embeddedProps = decodeURIComponent(
                    host.dataset.embeddedProps,
                );
            }
            if (host.dataset.embeddedState) {
                host.dataset.embeddedState = decodeURIComponent(
                    host.dataset.embeddedState,
                );
            }
        }
        return elem;
    }
}
