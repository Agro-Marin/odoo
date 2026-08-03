// @ts-check
/** @odoo-module native */

/** @module @web/search/embedded_actions_bar/embedded_actions_bar */

import {
    Component,
    reactive,
    useComponent,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { AccordionItem } from "@web/components/dropdown/accordion_item";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { useDropdownState } from "@web/components/dropdown/dropdown_hooks";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { useAction } from "@web/core/action_port";
import { browser } from "@web/core/browser/browser";
import { makeContext } from "@web/core/context";
import { Transition } from "@web/core/transition";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useSortable } from "@web/core/utils/dnd/sortable_owl";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";

/**
 * @typedef EmbeddedAction
 * @property {number} id
 * @property {[number, string]} parent_action_id
 * @property {string} name
 * @property {number} [sequence]
 * @property {number} [parent_res_id]
 * @property {string} parent_res_model
 * @property {[number, string]} action_id
 * @property {string} [python_method]
 * @property {number} [user_id]
 * @property {boolean} [is_deletable]
 * @property {string} [default_view_mode]
 * @property {string} [filter_ids]
 * @property {string} [domain]
 * @property {string} [context]
 * @property {any} [group_ids]
 */

export class EmbeddedActionsConfigHandler {
    /**
     * @param {number|string} parentActionId
     * @param {number|false} currentActiveId
     * @param {string} parentResModel
     * @param {Object} ormService
     * @param {Object} notificationService
     */
    constructor(
        parentActionId,
        currentActiveId,
        parentResModel,
        ormService,
        notificationService,
    ) {
        this.parentActionId = parentActionId;
        this.currentActiveId = currentActiveId;
        this.parentResModel = parentResModel;
        this.embeddedActionsKey = `${this.parentActionId}+${this.currentActiveId || ""}`;
        this.embeddedActionsConfig = user.settings.embedded_actions_config_ids || {};
        this.orm = ormService;
        this.notification = notificationService;
        this._writeQueue = Promise.resolve();
    }

    /**
     * @param {Object} config
     * @returns {Promise<boolean>}
     */
    async setEmbeddedActionsConfig(config) {
        config = structuredClone(config);
        const run = async () => {
            const hadConfig = this.embeddedActionsKey in this.embeddedActionsConfig;
            const previousConfig = hadConfig
                ? structuredClone(this.embeddedActionsConfig[this.embeddedActionsKey])
                : null;
            if (hadConfig) {
                Object.assign(
                    this.embeddedActionsConfig[this.embeddedActionsKey],
                    config,
                );
            } else {
                this.embeddedActionsConfig[this.embeddedActionsKey] = config;
            }
            try {
                await this.orm.call(
                    "res.users.settings",
                    "set_embedded_actions_setting",
                    [
                        user.settings.id,
                        this.parentActionId,
                        this.currentActiveId,
                        config,
                    ],
                );
                return true;
            } catch {
                if (hadConfig) {
                    this.embeddedActionsConfig[this.embeddedActionsKey] =
                        previousConfig;
                } else {
                    delete this.embeddedActionsConfig[this.embeddedActionsKey];
                }
                this.notification.add(
                    _t("Failed to save the embedded actions configuration."),
                    { type: "danger" },
                );
                return false;
            }
        };
        this._writeQueue = this._writeQueue || Promise.resolve();
        const result = this._writeQueue.then(run, run);
        this._writeQueue = result.catch(() => {});
        return result;
    }

    /**
     * @param {string} key
     * @returns {any}
     */
    getEmbeddedActionsConfig(key) {
        return this.embeddedActionsConfig[this.embeddedActionsKey]?.[key];
    }

    /** @returns {boolean} */
    hasEmbeddedActionsConfig() {
        return this.embeddedActionsKey in this.embeddedActionsConfig;
    }

    /** @returns {Promise<Object>} */
    async fetchEmbeddedActionsConfig() {
        return await this.orm.call(
            "res.users.settings",
            "get_embedded_actions_settings",
            [user.settings.id],
            {
                context: {
                    res_model: this.parentResModel,
                    res_id: this.currentActiveId,
                },
            },
        );
    }

    /** @param {Object} newSettings */
    updateEmbeddedActionsConfig(newSettings) {
        for (const [key, value] of Object.entries(newSettings)) {
            this.embeddedActionsConfig[key] = value;
        }
    }
}

export class EmbeddedActions {
    /**
     * @param {Object} params
     * @param {Object} params.env
     * @param {Object} params.orm
     * @param {Object} params.notification
     * @param {Object} params.dialog
     * @param {Object} params.action
     */
    constructor({ env, orm, notification, dialog, action }) {
        this.env = env;
        this.orm = orm;
        this.notificationService = notification;
        this.dialogService = dialog;
        this.actionService = action;

        this.defaultEmbeddedActions = env.config.embeddedActions;
        if (env.config.embeddedActions?.length > 0 && !env.config.parentActionId) {
            const { parent_res_model, parent_action_id } =
                env.config.embeddedActions[0];
            this.defaultEmbeddedActions = [
                {
                    id: false,
                    name: env.config?.actionName,
                    parent_action_id,
                    parent_res_model,
                    action_id: parent_action_id,
                    user_id: false,
                    context: {},
                },
                ...env.config.embeddedActions,
            ];
        }

        const parentActionId =
            env.config.parentActionId ||
            env.config.embeddedActions?.[0]?.parent_action_id[0] ||
            env.config.embeddedActions?.[0]?.parent_action_id ||
            "";
        const currentActiveId = env.searchModel?.globalContext.active_id || false;
        this.configHandler = new EmbeddedActionsConfigHandler(
            parentActionId,
            currentActiveId,
            this.currentEmbeddedAction?.parent_res_model,
            this.orm,
            this.notificationService,
        );

        /**
         * @type {{showEmbedded: boolean, embeddedActions: EmbeddedAction[], newActionIsShared: boolean, newActionName: string, visibleEmbeddedActions: (number|false)[], currentEmbeddedAction: EmbeddedAction}}
         */
        this.embeddedInfos = reactive({
            showEmbedded:
                !!this.configHandler.getEmbeddedActionsConfig("embedded_visibility"),
            embeddedActions: this.defaultEmbeddedActions || [],
            newActionIsShared: false,
            newActionName: this.defaultNewActionName,
            visibleEmbeddedActions: [
                ...(this.configHandler.getEmbeddedActionsConfig(
                    "embedded_actions_visibility",
                ) || []),
            ],
            currentEmbeddedAction: this.currentEmbeddedAction,
        });

        const embeddedOrder = this.configHandler.getEmbeddedActionsConfig(
            "embedded_actions_order",
        );
        if (embeddedOrder) {
            this.sortActions(embeddedOrder);
        }
    }

    /**
     * @returns {EmbeddedAction}
     */
    get currentEmbeddedAction() {
        if (!this.env.config) {
            return /** @type {any} */ ({});
        }
        const { currentEmbeddedActionId } = this.env.config;
        return (
            this.defaultEmbeddedActions?.find(
                ({ id }) => id === currentEmbeddedActionId,
            ) || this.defaultEmbeddedActions?.[0]
        );
    }

    /** @returns {string} */
    get defaultNewActionName() {
        if (this.currentEmbeddedAction?.name) {
            return _t("Custom %s", this.currentEmbeddedAction.name);
        } else {
            return _t("Custom Embedded Action");
        }
    }

    /**
     * @param {EmbeddedAction} action
     * @returns {boolean}
     */
    isActionVisible(action) {
        return this.embeddedInfos.visibleEmbeddedActions.includes(action.id);
    }

    async toggleBar() {
        if (this._togglingBar) {
            return;
        }
        this._togglingBar = true;
        const showEmbedded = !this.embeddedInfos.showEmbedded;
        try {
            await this._applyBarVisibility(showEmbedded);
            this.embeddedInfos.showEmbedded = showEmbedded;
        } finally {
            this._togglingBar = false;
        }
    }

    /** @param {boolean} showEmbedded */
    async _applyBarVisibility(showEmbedded) {
        if (showEmbedded && !this.configHandler.hasEmbeddedActionsConfig()) {
            const embeddedSettings =
                await this.configHandler.fetchEmbeddedActionsConfig();
            if (this.configHandler.embeddedActionsKey in embeddedSettings) {
                this.configHandler.updateEmbeddedActionsConfig(embeddedSettings);
                this.embeddedInfos.visibleEmbeddedActions = [
                    ...(this.configHandler.getEmbeddedActionsConfig(
                        "embedded_actions_visibility",
                    ) || []),
                ];
                const embeddedOrder = this.configHandler.getEmbeddedActionsConfig(
                    "embedded_actions_order",
                );
                if (embeddedOrder) {
                    this.sortActions(embeddedOrder);
                }
                await this.configHandler.setEmbeddedActionsConfig({
                    embedded_visibility: true,
                });
            } else {
                const config = {
                    res_model:
                        this.embeddedInfos.currentEmbeddedAction.parent_res_model,
                    embedded_actions_visibility: [],
                    embedded_visibility: true,
                    embedded_actions_order: [],
                };
                if (this.embeddedInfos.embeddedActions?.length > 0) {
                    const embeddedActionKey =
                        this.embeddedInfos.currentEmbeddedAction?.id || false;
                    if (
                        !this.embeddedInfos.visibleEmbeddedActions.includes(
                            embeddedActionKey,
                        )
                    ) {
                        this.embeddedInfos.visibleEmbeddedActions = [
                            ...this.embeddedInfos.visibleEmbeddedActions,
                            embeddedActionKey,
                        ];
                        config.embedded_actions_visibility = [
                            ...this.embeddedInfos.visibleEmbeddedActions,
                        ];
                    }
                }
                await this.configHandler.setEmbeddedActionsConfig(config);
            }
        } else {
            await this.configHandler.setEmbeddedActionsConfig({
                embedded_visibility: showEmbedded,
            });
        }
    }

    /**
     * @param {number|false} actionId
     * @returns {Promise<void>}
     */
    async toggleActionVisibility(actionId) {
        const wasVisible = this.embeddedInfos.visibleEmbeddedActions.includes(actionId);
        this.embeddedInfos.visibleEmbeddedActions = wasVisible
            ? this.embeddedInfos.visibleEmbeddedActions.filter((id) => id !== actionId)
            : [...this.embeddedInfos.visibleEmbeddedActions, actionId];
        const saved = await this.configHandler.setEmbeddedActionsConfig({
            embedded_actions_visibility: [...this.embeddedInfos.visibleEmbeddedActions],
        });
        if (!saved) {
            const current = this.embeddedInfos.visibleEmbeddedActions;
            this.embeddedInfos.visibleEmbeddedActions = wasVisible
                ? [...current, actionId]
                : current.filter((id) => id !== actionId);
        }
    }

    /**
     * @returns {Promise<boolean>}
     */
    async saveNewAction() {
        const {
            newActionName,
            newActionIsShared,
            embeddedActions,
            currentEmbeddedAction,
            visibleEmbeddedActions,
        } = this.embeddedInfos;
        if (!newActionName) {
            this.notificationService.add(
                _t("A name for your new action is required."),
                {
                    type: "danger",
                },
            );
            return false;
        }
        const duplicateName = embeddedActions.some(
            ({ name }) => name === newActionName,
        );
        if (duplicateName) {
            this.notificationService.add(
                _t("An action with the same name already exists."),
                {
                    type: "danger",
                },
            );
            return false;
        }
        const userId = newActionIsShared ? false : user.userId;

        const {
            parent_action_id,
            action_id,
            parent_res_model,
            python_method,
            domain,
            context,
            group_ids,
        } = currentEmbeddedAction;
        const values = {
            parent_action_id: parent_action_id[0] || parent_action_id,
            parent_res_model,
            parent_res_id: this.env.searchModel.globalContext.active_id,
            user_id: userId,
            is_deletable: true,
            default_view_mode: this.env.config.viewType,
            domain,
            context,
            group_ids,
            name: newActionName,
        };
        if (python_method) {
            values.python_method = python_method;
        } else {
            values.action_id = action_id?.[0] || action_id || this.env.config.actionId;
        }
        const [embeddedActionId] = await this.orm.create("ir.embedded.actions", [
            values,
        ]);
        const description = `${newActionName}`;
        await this.env.searchModel.createNewFavorite({
            description,
            isDefault: true,
            isShared: newActionIsShared,
            embeddedActionId,
        });
        Object.assign(this.embeddedInfos, {
            newActionName: "",
            newActionIsShared: false,
        });
        const enrichedNewEmbeddedAction = /** @type {EmbeddedAction} */ ({
            ...values,
            parent_action_id,
            action_id,
            id: embeddedActionId,
        });
        this.embeddedInfos.embeddedActions = [
            ...this.embeddedInfos.embeddedActions,
            enrichedNewEmbeddedAction,
        ];
        this.embeddedInfos.visibleEmbeddedActions = [
            ...visibleEmbeddedActions,
            embeddedActionId,
        ];
        const order = this.embeddedInfos.embeddedActions.map((el) => el.id);
        const saved = await this.configHandler.setEmbeddedActionsConfig({
            embedded_actions_visibility: [...this.embeddedInfos.visibleEmbeddedActions],
            embedded_actions_order: order,
        });
        if (!saved) {
            this.notificationService.add(
                _t("The action was created, but saving its position failed."),
                { type: "warning" },
            );
        }
        this.embeddedInfos.currentEmbeddedAction = enrichedNewEmbeddedAction;
        this.embeddedInfos.newActionName = `${newActionName} Custom`;
        return true;
    }

    /**
     * @param {EmbeddedAction} action
     */
    confirmDelete(action) {
        const dialogProps = {
            title: _t("Warning"),
            body: action.user_id
                ? _t("Are you sure that you want to remove this embedded action?")
                : _t(
                      "This embedded action is global and will be removed for everyone.",
                  ),
            confirmLabel: _t("Delete"),
            confirm: async () => await this.deleteAction(action),
            cancel: () => {},
        };
        this.dialogService.add(ConfirmationDialog, dialogProps);
    }

    /**
     * @param {EmbeddedAction} action
     */
    async deleteAction(action) {
        const { visibleEmbeddedActions, embeddedActions, currentEmbeddedAction } =
            this.embeddedInfos;
        await this.orm.unlink("ir.embedded.actions", [action.id]);
        this.embeddedInfos.visibleEmbeddedActions = visibleEmbeddedActions.filter(
            (id) => id !== action.id,
        );
        this.embeddedInfos.embeddedActions = embeddedActions.filter(
            ({ id }) => id !== action.id,
        );
        const order = this.embeddedInfos.embeddedActions.map((el) => el.id);
        await this.configHandler.setEmbeddedActionsConfig({
            embedded_actions_visibility: [...this.embeddedInfos.visibleEmbeddedActions],
            embedded_actions_order: order,
        });
        if (action.id === currentEmbeddedAction?.id) {
            const { active_id, active_model } = this.env.searchModel.globalContext;
            const actionContext = action.context ? makeContext([action.context]) : {};
            const additionalContext = {
                ...actionContext,
                active_id,
                active_model,
            };
            this.actionService.doAction(
                action.parent_action_id[0] || action.parent_action_id,
                {
                    additionalContext,
                    stackPosition: "replaceCurrentAction",
                },
            );
        }
    }

    /**
     * @param {EmbeddedAction} action
     */
    async openAction(action) {
        const { active_id, active_model } = this.env.searchModel.globalContext;
        const actionContext = action.context ? makeContext([action.context]) : {};
        const context = {
            ...actionContext,
            active_id,
            active_model,
            current_embedded_action_id: action.id,
            parent_action_embedded_actions: this.embeddedInfos.embeddedActions,
            parent_action_id: action.parent_action_id[0] || action.parent_action_id,
        };
        this.actionService.doActionButton(
            {
                type: action.python_method ? "object" : "action",
                resId: this.env.searchModel?.globalContext.active_id,
                name: action.python_method || action.action_id[0] || action.action_id,
                resModel: action.parent_res_model,
                context,
                stackPosition: "replaceCurrentAction",
                viewType: action.default_view_mode,
            },
            { isEmbeddedAction: true },
        );
    }

    /**
     * @param {(number|false)[]} order
     */
    sortActions(order) {
        this.embeddedInfos.embeddedActions = [
            ...this.embeddedInfos.embeddedActions,
        ].sort((a, b) => {
            const indexA = order.indexOf(a.id);
            const indexB = order.indexOf(b.id);
            if (indexA === -1 && indexB === -1) {
                return 0;
            }
            if (indexA === -1) {
                return 1;
            }
            if (indexB === -1) {
                return -1;
            }
            return indexA - indexB;
        });
    }

    /**
     * Buttons carry their position in `embeddedActions`, not their action id:
     * the main action's id is `false`, and OWL removes a `t-att-` attribute
     * whose value is `false` rather than rendering it, so an id read back from
     * the DOM is `undefined` for exactly the action this reorders.
     *
     * @param {Object} params
     * @param {HTMLElement} params.element
     * @param {HTMLElement} [params.previous]
     */
    async reorderFromDrop({ element, previous }) {
        const actions = this.embeddedInfos.embeddedActions;
        /** @param {HTMLElement} [el] */
        const positionOf = (el) => {
            const position = Number(el?.dataset.embeddedIndex);
            return Number.isInteger(position) && actions[position] ? position : -1;
        };
        const elementIndex = positionOf(element);
        if (elementIndex === -1) {
            return;
        }
        const previousIndex = positionOf(previous);
        const order = actions.map((el) => el.id);
        const elementId = order[elementIndex];
        const previousId = previousIndex === -1 ? undefined : order[previousIndex];
        const previousActions = [...actions];
        order.splice(elementIndex, 1);
        // `indexOf` is taken after the removal, so it is the post-splice seat.
        const insertAt = previousIndex === -1 ? 0 : order.indexOf(previousId) + 1;
        order.splice(insertAt, 0, elementId);
        this.sortActions(order);
        const saved = await this.configHandler.setEmbeddedActionsConfig({
            embedded_actions_order: order,
        });
        if (!saved) {
            this.embeddedInfos.embeddedActions = previousActions;
        }
    }
}

/**
 * @returns {EmbeddedActions | null}
 */
export function useEmbeddedActions() {
    const component = useComponent();
    const { env } = component;
    if (!(env.config?.embeddedActions?.length > 0)) {
        return null;
    }
    return new EmbeddedActions({
        env,
        orm: useService("orm"),
        notification: useService("notification"),
        dialog: useService("dialog"),
        action: useAction(),
    });
}

export class EmbeddedActionsBar extends Component {
    static template = "web.EmbeddedActionsBar";
    static components = {
        Dropdown,
        DropdownItem,
        AccordionItem,
        CheckBox,
        Transition,
    };
    static props = {
        embeddedActions: EmbeddedActions,
        isActionVisible: Function,
    };

    /** @type {{el: HTMLElement | null}} */
    root;
    /** @type {{el: HTMLElement | null}} */
    newActionNameRef;
    /** @type {import("@web/components/dropdown/dropdown_hooks").DropdownState} */
    embeddedActionsDropdown;
    /** @type {{embeddedInfos: EmbeddedActions["embeddedInfos"]}} */
    state;

    setup() {
        this.root = useRef("root");
        this.newActionNameRef = useRef("newActionNameRef");
        this.embeddedActionsDropdown = useDropdownState();
        this.state = useState({
            embeddedInfos: this.props.embeddedActions.embeddedInfos,
        });

        useEffect(
            (showEmbedded) => {
                const timer = browser.setTimeout(() => {
                    if (
                        showEmbedded &&
                        this.state.embeddedInfos.visibleEmbeddedActions.length === 1
                    ) {
                        this.embeddedActionsDropdown.open();
                    }
                }, 100);
                return () => browser.clearTimeout(timer);
            },
            () => [this.state.embeddedInfos.showEmbedded],
        );

        useSortable(
            /** @type {any} */ ({
                enable: true,
                ref: this.root,
                elements: ".o_draggable",
                cursor: "move",
                delay: 200,
                tolerance: 10,
                onWillStartDrag: ({ element, addClass }) =>
                    addClass(element, "o_dragged_embedded_action"),
                onDrop: (params) => this.props.embeddedActions.reorderFromDrop(params),
            }),
        );
    }

    /**
     * @param {EmbeddedAction} action
     * @returns {boolean}
     */
    _isEmbeddedActionVisible(action) {
        const { visibleEmbeddedActions } = this.state.embeddedInfos;
        return visibleEmbeddedActions && this.props.isActionVisible(action);
    }

    /**
     * @param {EmbeddedAction} action
     * @returns {string}
     */
    getDropdownClass(action) {
        return (!this.env.isSmall && this._isEmbeddedActionVisible(action)) ||
            (this.env.isSmall &&
                this.state.embeddedInfos.currentEmbeddedAction?.id === action.id)
            ? "selected"
            : "";
    }

    /**
     * @param {EmbeddedAction} action
     */
    onEmbeddedActionClick(action) {
        return this.props.embeddedActions.openAction(action);
    }

    /**
     * @param {number|false} actionId
     */
    _setVisibility(actionId) {
        return this.props.embeddedActions.toggleActionVisibility(actionId);
    }

    /**
     * @param {EmbeddedAction} action
     */
    openConfirmationDialog(action) {
        return this.props.embeddedActions.confirmDelete(action);
    }

    /**
     * @param {KeyboardEvent} ev
     * @param {EmbeddedAction} action
     */
    onDeleteKeydown(ev, action) {
        if (ev.key !== "Enter" && ev.key !== " ") {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.openConfirmationDialog(action);
    }

    _onShareCheckboxChange() {
        this.state.embeddedInfos.newActionIsShared =
            !this.state.embeddedInfos.newActionIsShared;
    }

    /**
     * @param {Event} ev
     */
    async _saveNewAction(ev) {
        const saved = await this.props.embeddedActions.saveNewAction();
        if (!saved) {
            ev.stopPropagation();
            this.newActionNameRef.el?.focus();
        }
    }
}
