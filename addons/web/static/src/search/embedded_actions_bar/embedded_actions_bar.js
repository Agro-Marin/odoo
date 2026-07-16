// @ts-check
/** @odoo-module native */

/** @module @web/search/embedded_actions_bar/embedded_actions_bar - Embedded actions tab bar: per-user visibility, ordering, creation and deletion of embedded actions */

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
import { Transition } from "@web/components/transition";
import { browser } from "@web/core/browser/browser";
import { makeContext } from "@web/core/context";
import { _t } from "@web/core/l10n/translation";
import { useSortable } from "@web/core/utils/dnd/sortable_owl";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/services/user";
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

/**
 * Manages per-user embedded action visibility, ordering, and configuration.
 *
 * Persists settings to `res.users.settings` keyed by `parentActionId+activeId`.
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
        // Read-only: `user.settings` is a shared (often deep-frozen) session
        // object, so assigning back to it (`??=`) throws. A fresh `|| {}` means
        // config mutations made before the server first returns this key don't
        // survive a remount, but that edge case isn't worth writing to a frozen
        // object; a session-shared store would be the way to fix it if needed.
        this.embeddedActionsConfig = user.settings.embedded_actions_config_ids || {};
        this.orm = ormService;
        this.notification = notificationService;
        // Serializes the write RPCs: two quick mutations (toggle + toggle, or
        // drag + toggle) fired independent res.users.settings writes whose
        // responses could resolve out of order, leaving the server on the
        // FIRST request's state while the UI shows the second. Chaining them
        // makes the last write win server-side too.
        this._writeQueue = Promise.resolve();
    }

    /**
     * @param {Object} config - partial config to merge (e.g.
     *  { embedded_visibility: true }); must be plain serializable data —
     *  callers pass copies, never live reactive arrays
     * @returns {Promise<boolean>} never rejects: on failure, the local cache
     *  is reverted, a notification is shown and `false` is returned
     */
    async setEmbeddedActionsConfig(config) {
        // Deep-copy both the incoming config and the revert snapshot: a
        // shallow copy would alias caller-owned arrays (the main payload), so
        // the cache would track later caller mutations and the failure revert
        // would restore the already-mutated array.
        config = structuredClone(config);
        const run = async () => {
            // Snapshot + apply the optimistic cache merge here, inside the
            // queued unit, NOT at call time: overlapping writes must each
            // read/snapshot/mutate the shared cache in commit order. Capturing
            // the revert snapshot at call time let an EARLIER write's deferred
            // failure revert restore a stale snapshot and wipe a LATER (already
            // applied) write's changes — breaking the documented last-write-wins.
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
                // Revert the local cache so it stays in sync with the server.
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
        // Run after any in-flight write (the queue never rejects, so a prior
        // failure doesn't stall the chain). Lazily initialized so the handler
        // works regardless of how it was constructed.
        this._writeQueue = this._writeQueue || Promise.resolve();
        const result = this._writeQueue.then(run, run);
        this._writeQueue = result.catch(() => {});
        return result;
    }

    /**
     * @param {string} key - config key (e.g. "embedded_visibility", "embedded_actions_order")
     * @returns {any}
     */
    getEmbeddedActionsConfig(key) {
        return this.embeddedActionsConfig[this.embeddedActionsKey]?.[key];
    }

    /** @returns {boolean} whether a config entry exists for this action+activeId key */
    hasEmbeddedActionsConfig() {
        return this.embeddedActionsKey in this.embeddedActionsConfig;
    }

    /** @returns {Promise<Object>} embedded actions settings from the database */
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

    /** @param {Object} newSettings - settings map to merge into local cache */
    updateEmbeddedActionsConfig(newSettings) {
        for (const [key, value] of Object.entries(newSettings)) {
            this.embeddedActionsConfig[key] = value;
        }
    }
}

/**
 * Holds the embedded actions state shared between the ControlPanel (toggle
 * button, mobile dropdown) and the EmbeddedActionsBar (desktop tab bar), and
 * implements every embedded-action behavior: show/hide persistence, per-action
 * visibility, creation ("Save View"), deletion, reordering, and execution.
 *
 * The reactive `embeddedInfos` object is the single source of truth; each
 * component subscribes to it with `useState`.
 */
export class EmbeddedActions {
    /**
     * @param {Object} params
     * @param {Object} params.env - component env (config, searchModel)
     * @param {Object} params.orm
     * @param {Object} params.notification
     * @param {Object} params.dialog
     * @param {Object} params.action - action service
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

        /** @type {{showEmbedded: boolean, embeddedActions: EmbeddedAction[], newActionIsShared: boolean, newActionName: string, visibleEmbeddedActions: (number|false)[], currentEmbeddedAction: EmbeddedAction}} */
        this.embeddedInfos = reactive({
            showEmbedded:
                !!this.configHandler.getEmbeddedActionsConfig("embedded_visibility"),
            embeddedActions: this.defaultEmbeddedActions || [],
            newActionIsShared: false,
            newActionName: this.defaultNewActionName,
            // Copy: the reactive state must not alias the cached settings
            // array, or in-place toggles would mutate the cache before its
            // revert snapshot is taken.
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

    /** @returns {string} default name for a new embedded action */
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

    /**
     * Show or hide the embedded actions bar, persisting `embedded_visibility`.
     * On first display without a locally cached config, syncs the config from
     * the database (it may have been changed from another browser session).
     */
    async toggleBar() {
        // Re-entrancy guard + capture the target once: with the target read
        // before the awaits and the flip after them, a double-click would
        // persist `true` twice then flip the local flag twice — hiding the
        // bar locally while the server says visible.
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

    /** @param {boolean} showEmbedded target visibility being persisted */
    async _applyBarVisibility(showEmbedded) {
        if (showEmbedded && !this.configHandler.hasEmbeddedActionsConfig()) {
            // No local config yet: fetch from DB (it may have changed from
            // another browser session) and sync the browser cache with it.
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
                // Store a new embedded actions config if still not found in the settings
                const config = {
                    res_model:
                        this.embeddedInfos.currentEmbeddedAction.parent_res_model,
                    embedded_actions_visibility: [],
                    embedded_visibility: true,
                    embedded_actions_order: [],
                };
                // If there is no visible embedded actions, the current action (if it exists) is put by default
                if (this.embeddedInfos.embeddedActions?.length > 0) {
                    const embeddedActionKey =
                        this.embeddedInfos.currentEmbeddedAction?.id || false;
                    if (
                        !this.embeddedInfos.visibleEmbeddedActions.includes(
                            embeddedActionKey,
                        )
                    ) {
                        this.embeddedInfos.visibleEmbeddedActions.push(
                            embeddedActionKey,
                        );
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
     * Toggles an action's visibility in the cached visibleEmbeddedActions
     * list (avoids re-parsing user settings on every access) and persists it.
     * On persistence failure the visible UI is restored too, so it cannot
     * silently diverge from the cache and the server.
     * @param {number|false} actionId
     * @returns {Promise<void>}
     */
    async toggleActionVisibility(actionId) {
        const previousVisible = [...this.embeddedInfos.visibleEmbeddedActions];
        const embeddedActionIndex =
            this.embeddedInfos.visibleEmbeddedActions.indexOf(actionId);
        if (embeddedActionIndex !== -1) {
            this.embeddedInfos.visibleEmbeddedActions.splice(embeddedActionIndex, 1);
        } else {
            this.embeddedInfos.visibleEmbeddedActions.push(actionId);
        }
        const saved = await this.configHandler.setEmbeddedActionsConfig({
            embedded_actions_visibility: [...this.embeddedInfos.visibleEmbeddedActions],
        });
        if (!saved) {
            this.embeddedInfos.visibleEmbeddedActions = previousVisible;
        }
    }

    /**
     * Creates a new embedded action from the current view state, together with
     * a default favorite carrying the current search context.
     *
     * @returns {Promise<boolean>} false when the name is missing or duplicated
     *  (a danger notification is shown), true on success
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
            // May be an [id, name] tuple (server rows) or a bare numeric id
            // (the synthetic parent entry built by executeActionButton) —
            // same normalization as openAction/deleteAction.
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
        this.embeddedInfos.embeddedActions.push(enrichedNewEmbeddedAction);
        visibleEmbeddedActions.push(embeddedActionId);
        const order = this.embeddedInfos.embeddedActions.map((el) => el.id);
        const saved = await this.configHandler.setEmbeddedActionsConfig({
            embedded_actions_visibility: [...visibleEmbeddedActions],
            embedded_actions_order: order,
        });
        if (!saved) {
            // The action itself was created server-side (orm.create +
            // createNewFavorite above), so we do NOT revert the local push the
            // way toggleActionVisibility does — that would hide a record that
            // now exists and would reappear on reload. Persisting its
            // visibility/order failed, though, so surface it instead of
            // silently reporting success.
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
     * Asks for confirmation before deleting the given embedded action.
     *
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
        // Delete on the server first: if unlink is refused (e.g. ACL), it throws
        // before we mutate local state or persist visibility/order, so the tab
        // stays and res.users.settings keeps referencing the still-existing action.
        await this.orm.unlink("ir.embedded.actions", [action.id]);
        const embeddedActionIndex = visibleEmbeddedActions.indexOf(action.id);
        if (embeddedActionIndex !== -1) {
            visibleEmbeddedActions.splice(embeddedActionIndex, 1);
        }
        this.embeddedInfos.embeddedActions = embeddedActions.filter(
            ({ id }) => id !== action.id,
        );
        const order = this.embeddedInfos.embeddedActions.map((el) => el.id);
        await this.configHandler.setEmbeddedActionsConfig({
            embedded_actions_visibility: [...visibleEmbeddedActions],
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
     * Executes the given embedded action, replacing the current action.
     *
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
        this.embeddedInfos.embeddedActions = this.embeddedInfos.embeddedActions.sort(
            (a, b) => {
                const indexA = order.indexOf(a.id);
                const indexB = order.indexOf(b.id);
                // Both missing from the persisted order: treat as equal.
                // Returning 1 for both (a,b) and (b,a) — as before — is an
                // inconsistent comparator (undefined sort behaviour).
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
            },
        );
    }

    /**
     * Computes and persists the new tab order after a drag-and-drop.
     *
     * @param {Object} params
     * @param {HTMLElement} params.element
     * @param {HTMLElement} [params.previous]
     */
    async reorderFromDrop({ element, previous }) {
        // Snapshot the pre-drop order so a persistence failure reverts the
        // dragged tab back (mirrors toggleActionVisibility, which awaits +
        // restores); a fire-and-forget write would leave the UI reordered
        // while the server kept the old order.
        const previousActions = [...this.embeddedInfos.embeddedActions];
        const order = this.embeddedInfos.embeddedActions.map((el) => el.id);
        const elementId = Number(element.dataset.id) || false;
        const elementIndex = order.indexOf(elementId);
        order.splice(elementIndex, 1);
        if (previous) {
            const prevIndex = order.indexOf(Number(previous.dataset.id) || false);
            order.splice(prevIndex + 1, 0, elementId);
        } else {
            order.splice(0, 0, elementId);
        }
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
 * Builds the embedded actions state for the current view, or returns `null`
 * when the action provides no embedded actions — in that case none of the
 * embedded machinery (config handler, reactive state, persistence) is set up.
 *
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
        action: useService("action"),
    });
}

/**
 * Desktop tab bar listing the visible embedded actions of the current action,
 * with drag-and-drop reordering and a configuration dropdown (per-action
 * visibility, "Save View").
 *
 * All state and behavior live in the shared {@link EmbeddedActions} model
 * owned by the ControlPanel; this component only renders the desktop bar.
 * `isActionVisible` is received as a prop (instead of read from the model)
 * so that ControlPanel subclasses overriding `_isEmbeddedActionVisible`
 * keep controlling the tabs' visibility.
 */
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

    // Class fields declared with @type so strictNullChecks treats them as
    // initialized. Real assignment happens in setup().
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

        // Automatically open the embedded actions dropdown when there is only
        // one visible embedded action. The timer delays the display of the
        // dropdown menu to avoid flicker issues.
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
        // Read visibleEmbeddedActions from the bar's OWN reactive state so that
        // a visibility toggle re-renders the tab bar directly, in the same
        // frame as the toggle. Delegating the decision solely to the prop
        // (which reads the parent ControlPanel's reactive) subscribed only the
        // ControlPanel, so the bar refreshed one frame late via the parent's
        // render cascade — after hoot's click settled (embedded_action
        // visibility tests saw the stale tab count). The result is still routed
        // through the prop so a ControlPanel subclass can override visibility.
        void this.state.embeddedInfos.visibleEmbeddedActions.includes(action.id);
        return this.props.isActionVisible(action);
    }

    /**
     * @param {EmbeddedAction} action
     * @returns {string} CSS class ("selected" or "")
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
