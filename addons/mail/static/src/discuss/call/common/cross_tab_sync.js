/** @odoo-module native */
import { browser } from "@web/core/browser/browser";

export const CROSS_TAB_HOST_MESSAGE = {
    PING: "PING",
    UPDATE_REMOTE: "UPDATE_REMOTE",
    CLOSE: "CLOSE",
    PIP_CHANGE: "PIP_CHANGE",
};
export const CROSS_TAB_CLIENT_MESSAGE = {
    INIT: "INIT",
    REQUEST_ACTION: "REQUEST_ACTION",
    LEAVE: "LEAVE",
    UPDATE_VOLUME: "UPDATE_VOLUME",
};
export const PING_INTERVAL = 30_000;

/**
 * @typedef {Object} CrossTabSyncHooks
 * @property {() => boolean} isHost
 * @property {(changes: Object) => void} onRemoteUpdate
 * @property {() => void} onHostClosed
 * @property {(isPipMode: boolean) => void} onPipChange
 * @property {() => void} onRemoteTabInit
 * @property {(changes: Object) => Promise} onActionRequest
 * @property {() => Promise} onLeaveRequest
 * @property {(changes: {sessionId: number, volume: number}) => void} onVolumeChange
 * @property {(entry: string, options?: Object) => void} log
 */
export class CrossTabSync {
    /** @type {BroadcastChannel|undefined} */
    _broadcastChannel;
    /** @type {number} */
    _crossTabTimeoutId;

    /**
     * @param {Object} param0
     * @param {import("@mail/discuss/call/common/rtc_service").RtcCallState} param0.state
     * @param {CrossTabSyncHooks} param0.hooks
     * @param {() => BroadcastChannel} [param0.createBroadcastChannel]
     */
    constructor({ state, hooks, createBroadcastChannel }) {
        this.state = state;
        this.hooks = hooks;
        this._broadcastChannel = (
            createBroadcastChannel ??
            (() => new browser.BroadcastChannel("call_sync_state"))
        )();
    }

    get isRemote() {
        return Boolean(this.state.remoteChannelId);
    }

    start() {
        if (this._broadcastChannel) {
            this._broadcastChannel.onmessage = this._onMessage.bind(this);
            this.post({ type: CROSS_TAB_CLIENT_MESSAGE.INIT });
        }
    }

    /** @param {Object} message */
    post(message) {
        if (!this._broadcastChannel) {
            this.hooks.log("broadcast channel not available");
            return;
        }
        try {
            this._broadcastChannel.postMessage(message);
        } catch (error) {
            this.hooks.log("failed to post message to broadcast channel", {
                error,
            });
        }
    }

    /** @param {number} sessionId */
    host(sessionId) {
        this.state.remoteChannelId = undefined;
        this.state.remoteSessionId = sessionId;
    }

    endHost() {
        this.post({
            type: CROSS_TAB_HOST_MESSAGE.CLOSE,
            hostedSessionId: this.state.remoteSessionId,
        });
    }

    /**
     * @param {number} channelId
     * @param {number} sessionId
     * @param {Object} changes
     */
    updateRemoteTabs(channelId, sessionId, changes) {
        this.post({
            type: CROSS_TAB_HOST_MESSAGE.UPDATE_REMOTE,
            hostedChannelId: channelId,
            hostedSessionId: sessionId,
            changes,
        });
    }

    /** @param {Object} changes */
    requestAction(changes) {
        this.post({
            type: CROSS_TAB_CLIENT_MESSAGE.REQUEST_ACTION,
            changes,
        });
    }

    requestLeave() {
        this.post({ type: CROSS_TAB_CLIENT_MESSAGE.LEAVE });
    }

    /** @param {number} sessionId */
    ping(sessionId) {
        this.post({
            type: CROSS_TAB_HOST_MESSAGE.PING,
            hostedSessionId: sessionId,
        });
    }

    /** @param {boolean} isPipMode */
    notifyPipChange(isPipMode) {
        this.post({
            type: CROSS_TAB_HOST_MESSAGE.PIP_CHANGE,
            changes: { isPipMode },
        });
    }

    /**
     * @param {number} sessionId
     * @param {number} volume
     */
    notifyVolume(sessionId, volume) {
        this.post({
            type: CROSS_TAB_CLIENT_MESSAGE.UPDATE_VOLUME,
            changes: { sessionId, volume },
        });
    }

    _refreshTimeout() {
        browser.clearTimeout(this._crossTabTimeoutId);
        this._crossTabTimeoutId = browser.setTimeout(() => {
            this.hooks.onHostClosed();
        }, PING_INTERVAL + 10_000);
    }

    /** @param {MessageEvent} ev */
    async _onMessage({ data: { type, hostedChannelId, hostedSessionId, changes } }) {
        switch (type) {
            case CROSS_TAB_HOST_MESSAGE.UPDATE_REMOTE:
                if (this.hooks.isHost()) {
                    return;
                }
                this.state.remoteSessionId = hostedSessionId;
                this.state.remoteChannelId = hostedChannelId;
                this._refreshTimeout();
                this.hooks.onRemoteUpdate(changes);
                return;
            case CROSS_TAB_HOST_MESSAGE.CLOSE: {
                if (
                    this.hooks.isHost() ||
                    this.state.remoteSessionId !== hostedSessionId
                ) {
                    return;
                }
                this.hooks.onHostClosed();
                return;
            }
            case CROSS_TAB_HOST_MESSAGE.PIP_CHANGE: {
                if (this.hooks.isHost()) {
                    return;
                }
                this.hooks.onPipChange(changes.isPipMode);
                return;
            }
            case CROSS_TAB_HOST_MESSAGE.PING: {
                if (!this.isRemote || this.state.remoteSessionId !== hostedSessionId) {
                    return;
                }
                this._refreshTimeout();
                return;
            }
            case CROSS_TAB_CLIENT_MESSAGE.INIT: {
                if (!this.hooks.isHost()) {
                    return;
                }
                this.hooks.onRemoteTabInit();
                return;
            }
            case CROSS_TAB_CLIENT_MESSAGE.REQUEST_ACTION: {
                if (!this.hooks.isHost()) {
                    return;
                }
                await this.hooks.onActionRequest(changes);
                return;
            }
            case CROSS_TAB_CLIENT_MESSAGE.LEAVE: {
                if (!this.hooks.isHost()) {
                    return;
                }
                await this.hooks.onLeaveRequest();
                return;
            }
            case CROSS_TAB_CLIENT_MESSAGE.UPDATE_VOLUME: {
                this.hooks.onVolumeChange(changes);
                return;
            }
        }
    }

    dispose() {
        browser.clearTimeout(this._crossTabTimeoutId);
        this.state.remoteSessionId = undefined;
        this.state.remoteChannelId = undefined;
    }
}
