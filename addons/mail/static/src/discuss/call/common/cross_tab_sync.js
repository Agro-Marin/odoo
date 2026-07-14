/** @odoo-module native */
import { browser } from "@web/core/browser/browser";

export const CROSS_TAB_HOST_MESSAGE = {
    PING: "PING", // signals that the host is still active
    UPDATE_REMOTE: "UPDATE_REMOTE", // sent with updated state of the remote rtc sessions of the call
    CLOSE: "CLOSE", // sent when the host ends the call
    PIP_CHANGE: "PIP_CHANGE", // sent when the host changes the pip mode
};
export const CROSS_TAB_CLIENT_MESSAGE = {
    INIT: "INIT", // sent by a tab to signal its presence and receive a state update
    REQUEST_ACTION: "REQUEST_ACTION", // request that an action be executed by the host (mute, deaf,...)
    LEAVE: "LEAVE", // request the host to leave the call
    UPDATE_VOLUME: "UPDATE_VOLUME", // sent by a tab to signal a volume change
};
export const PING_INTERVAL = 30_000;

/**
 * Delegate surface the coordinator (Rtc) provides to the cross-tab sync.
 *
 * @typedef {Object} CrossTabSyncHooks
 * @property {() => boolean} isHost whether the current tab hosts the call
 * @property {(changes: Object) => void} onRemoteUpdate session info payload
 *  received from the host tab
 * @property {() => void} onHostClosed the host ended the call (or timed out)
 * @property {(isPipMode: boolean) => void} onPipChange
 * @property {() => void} onRemoteTabInit a new tab asked for the host state
 * @property {(changes: Object) => Promise} onActionRequest a remote tab asked
 *  the host to run an action (mute, deaf,...)
 * @property {() => Promise} onLeaveRequest a remote tab asked to leave
 * @property {(changes: {sessionId: number, volume: number}) => void} onVolumeChange
 * @property {(entry: string, options?: Object) => void} log
 */

/**
 * Host/remote-action protocol between the tabs of the same browser: the tab
 * that owns the connections and streams (the host) mirrors its call state to
 * the other tabs and executes the actions they request. The remote host ids
 * live in the shared reactive `state` (`remoteSessionId`, `remoteChannelId`)
 * so the coordinator's computed fields track them.
 */
export class CrossTabSync {
    /** @type {BroadcastChannel|undefined} */
    _broadcastChannel;
    /** @type {number} timeout after which a silent host is considered gone */
    _crossTabTimeoutId;

    /**
     * @param {Object} param0
     * @param {Object} param0.state shared reactive call state; the sync owns
     *  the `remoteSessionId` / `remoteChannelId` slots and writes `isPipMode`
     * @param {CrossTabSyncHooks} param0.hooks
     * @param {() => BroadcastChannel} [param0.createBroadcastChannel]
     *  injectable channel factory
     */
    constructor({ state, hooks, createBroadcastChannel }) {
        this.state = state;
        this.hooks = hooks;
        this._broadcastChannel = (
            createBroadcastChannel ??
            (() => new browser.BroadcastChannel("call_sync_state"))
        )();
    }

    /**
     * Whether this tab serves as a remote for a call hosted on another tab.
     */
    get isRemote() {
        return Boolean(this.state.remoteChannelId);
    }

    /**
     * Starts listening to the other tabs and signals this tab's presence.
     */
    start() {
        if (this._broadcastChannel) {
            this._broadcastChannel.onmessage = this._onMessage.bind(this);
            this.post({ type: CROSS_TAB_CLIENT_MESSAGE.INIT });
        }
    }

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

    /**
     * Marks this tab as the host of the call.
     *
     * @param {number} sessionId id of the local rtc session
     */
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
     * Sends the updated state of the call sessions to the other tabs.
     *
     * @param {number} channelId
     * @param {number} sessionId id of the local (hosting) rtc session
     * @param {Object} changes session info payloads by session id
     */
    updateRemoteTabs(channelId, sessionId, changes) {
        this.post({
            type: CROSS_TAB_HOST_MESSAGE.UPDATE_REMOTE,
            hostedChannelId: channelId,
            hostedSessionId: sessionId,
            changes,
        });
    }

    /**
     * Requests that an action be executed by the host tab of the call.
     *
     * @param {Object} changes
     */
    requestAction(changes) {
        this.post({
            type: CROSS_TAB_CLIENT_MESSAGE.REQUEST_ACTION,
            changes,
        });
    }

    requestLeave() {
        this.post({ type: CROSS_TAB_CLIENT_MESSAGE.LEAVE });
    }

    /** @param {number} sessionId id of the local (hosting) rtc session */
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
                if (this.state.remoteSessionId !== hostedSessionId) {
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

    /**
     * Resets the per-call cross-tab state. The BroadcastChannel itself stays
     * open: it is shared by every call over the lifetime of the tab.
     */
    dispose() {
        browser.clearTimeout(this._crossTabTimeoutId);
        this.state.remoteSessionId = undefined;
        this.state.remoteChannelId = undefined;
    }
}
