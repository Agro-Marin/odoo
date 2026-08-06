// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_save_coordinator */

import { SignalStore } from "@web/core/utils/reactive";

/**
 * @typedef {"clean" | "dirty" | "saving" | "error"} FormSaveStatus
 * @typedef {"begin" | "ok" | "recoverable" | "failed" | "discard"} FormSaveEvent
 * @typedef {{
 *   onSaveError: (error: any, callbacks: { discard: () => any, retry: () => any }) => any,
 *   onUrgentSaveFailed?: () => void,
 *   recoverFromSaveError?: (error: any, model: any) => boolean,
 * }} FormSaveHooks
 * @typedef {{
 *   checkDirty?: boolean,
 *   reload?: boolean,
 *   nextId?: number,
 *   errorMode?: "dialog" | "rethrow" | "silent",
 *   saveOverride?: (record: any, params: any) => Promise<any>,
 *   params?: Record<string, any>,
 * }} RequestSaveOptions
 */

/**
 * @type {Record<FormSaveStatus, Partial<Record<FormSaveEvent, FormSaveStatus>>>}
 */
const TRANSITIONS = {
    clean: { begin: "saving", discard: "clean" },
    dirty: { begin: "saving", discard: "clean" },
    saving: {
        begin: "saving",
        ok: "clean",
        recoverable: "dirty",
        failed: "error",
        discard: "clean",
    },
    error: { begin: "saving", discard: "clean" },
};

export class InvalidFormSaveTransitionError extends Error {
    /**
     * @param {string} from
     * @param {string} event
     */
    constructor(from, event) {
        super(
            `FormSaveCoordinator: invalid transition '${event}' from state '${from}'`,
        );
        this.name = "InvalidFormSaveTransitionError";
        this.from = from;
        this.event = event;
    }
}

export class FormSaveCoordinator extends SignalStore {
    /** @type {FormSaveStatus} */
    status = "clean";

    /**
     * @type {any | null}
     */
    lastError = null;

    /**
     * @type {number}
     */
    _saveEpoch = 0;

    /**
     * @param {{ root: any }} model
     * @param {FormSaveHooks} hooks
     */
    constructor(model, hooks) {
        super();
        this.model = model;
        this.hooks = hooks;
    }

    /** @returns {boolean} */
    get isSaving() {
        return this.status === "saving";
    }

    /**
     * @param {FormSaveEvent} event
     */
    _transition(event) {
        const next = TRANSITIONS[this.status]?.[event];
        if (next === undefined) {
            throw new InvalidFormSaveTransitionError(this.status, event);
        }
        this.status = next;
    }

    /**
     * @param {FormSaveEvent} event
     * @param {number} ownerEpoch
     */
    _finishTransition(event, ownerEpoch) {
        if (ownerEpoch !== this._saveEpoch) {
            return;
        }
        this._transition(event);
        if (event === "ok") {
            // A save that ends up ok (e.g. the error dialog's "Discard" choice)
            // must not leave a stale error behind: consumers such as
            // shouldExecuteAction read lastError to decide whether to proceed.
            this.lastError = null;
        }
    }

    /**
     * @param {RequestSaveOptions} [options]
     * @returns {Promise<any>}
     */
    async requestSave({
        checkDirty = false,
        reload = true,
        nextId,
        errorMode = "dialog",
        saveOverride,
        params,
    } = {}) {
        if (checkDirty && !(await this.model.root.isDirty())) {
            return true;
        }
        this.lastError = null;
        this._transition("begin");
        const ownerEpoch = ++this._saveEpoch;
        /** @type {Record<string, any>} */
        const opts = { reload, ...params };
        if (nextId !== undefined) {
            opts.nextId = nextId;
        }
        try {
            let saved;
            if (saveOverride) {
                saved = await saveOverride(this.model.root, opts);
            } else {
                const onError = this._buildOnError(errorMode, ownerEpoch);
                if (onError) {
                    opts.onError = onError;
                }
                saved = await this.model.root.save(opts);
            }
            if (saved !== false) {
                this._finishTransition("ok", ownerEpoch);
                return saved;
            }
            this._finishTransition("recoverable", ownerEpoch);
            return false;
        } catch (e) {
            this._finishTransition("failed", ownerEpoch);
            if (ownerEpoch === this._saveEpoch) {
                this.lastError = e;
            }
            if (errorMode === "rethrow" || saveOverride) {
                throw e;
            }
            return false;
        }
    }

    /**
     * @returns {Promise<boolean>}
     */
    async requestUrgentSave() {
        if (this.isSaving) {
            const ownerEpoch = this._saveEpoch;
            try {
                const succeeded = await this.model.root.urgentSave();
                if (!succeeded) {
                    this.hooks.onUrgentSaveFailed?.();
                }
                return succeeded;
            } catch (e) {
                if (ownerEpoch === this._saveEpoch) {
                    this.lastError = e;
                }
                this.hooks.onUrgentSaveFailed?.();
                throw e;
            }
        }
        this._transition("begin");
        const ownerEpoch = ++this._saveEpoch;
        try {
            const succeeded = await this.model.root.urgentSave();
            if (succeeded) {
                this._finishTransition("ok", ownerEpoch);
            } else {
                if (ownerEpoch === this._saveEpoch) {
                    this.hooks.onUrgentSaveFailed?.();
                }
                this._finishTransition("failed", ownerEpoch);
            }
            return succeeded;
        } catch (e) {
            this._finishTransition("failed", ownerEpoch);
            if (ownerEpoch === this._saveEpoch) {
                this.lastError = e;
            }
            throw e;
        }
    }

    async requestDiscard() {
        const ownerEpoch = ++this._saveEpoch;
        await this.model.root.discard();
        if (ownerEpoch !== this._saveEpoch) {
            return;
        }
        this._transition("discard");
        this.lastError = null;
    }

    /**
     * @param {"dialog"|"rethrow"|"silent"} errorMode
     * @param {number} ownerEpoch
     * @returns {((error: any, callbacks: any) => any) | undefined}
     */
    _buildOnError(errorMode, ownerEpoch) {
        if (errorMode === "silent") {
            return undefined;
        }
        if (errorMode === "rethrow") {
            return async (error, callbacks) => {
                if (this.hooks.recoverFromSaveError?.(error, this.model)) {
                    return callbacks.retry();
                }
                throw error;
            };
        }
        return async (error, callbacks) => {
            if (this.hooks.recoverFromSaveError?.(error, this.model)) {
                return callbacks.retry();
            }
            if (!error?.data) {
                throw error;
            }
            if (ownerEpoch !== this._saveEpoch) {
                return false;
            }
            this.lastError = error;
            return await this.hooks.onSaveError(error, callbacks);
        };
    }
}
