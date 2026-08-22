/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { ancestors } from "@html_editor/utils/dom_traversal";
import { compareIds, generateId } from "@html_editor/utils/ids";
import { childNodeIndex } from "@html_editor/utils/position";
import { rpc } from "@web/core/network";
import { user } from "@web/core/user";
import { Mutex } from "@web/core/utils/concurrency";
import { debounce } from "@web/core/utils/timing";

import { PeerToPeer, RequestError } from "./PeerToPeer.js";

/**
 * @typedef {Object} CollaborationSelection
 * @property {import("@html_editor/core/history_plugin").SerializedSelection} selection
 * @property {string} color
 * @property {string} peerId
 */

const PTP_MAX_RECOVERY_TIME = 500;

const REQUEST_ERROR = Symbol("REQUEST_ERROR");

let ICE_SERVERS = null;

/**
 * @typedef { Object } CollaborationOdooShared
 * @property { CollaborationOdooPlugin['getPeerMetadata'] } getPeerMetadata
 */

export class CollaborationOdooPlugin extends Plugin {
    static id = "collaborationOdoo";
    static dependencies = ["baseContainer", "history", "collaboration", "selection"];
    static shared = ["getPeerMetadata"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        selectionchange_handlers: debounce(() => {
            this.ptp?.notifyAllPeers(
                "oe_history_set_selection",
                this.getCurrentCollaborativeSelection(),
                {
                    transport: "rtc",
                },
            );
        }, 50),
        clean_for_save_handlers: ({ root }) => this.attachHistoryIds(root),
        history_missing_parent_step_handlers:
            this.onHistoryMissingParentStep.bind(this),
        history_reset_handlers: this.onReset.bind(this),
        step_added_handlers: ({ step }) =>
            this.ptp?.notifyAllPeers("oe_history_step", step, { transport: "rtc" }),
    };

    setup() {
        this.isDocumentStale = false;

        this.ptpJoined = false;

        this.lastCollaborationResetId = 0;

        this.serverLastStepId =
            this.config.content && this.getLastHistoryStepId(this.config.content);

        this.setupCollaboration(this.config.collaboration.collaborationChannel);

        const collaborativeTrigger = this.config.collaboration.collaborativeTrigger;
        this.joinPeerToPeer = this.joinPeerToPeer.bind(this);
        if (collaborativeTrigger === "start") {
            this.joinPeerToPeer();
        } else if (
            collaborativeTrigger === "focus" ||
            typeof collaborativeTrigger === "undefined"
        ) {
            this.editable.addEventListener("focus", this.joinPeerToPeer);
        }

        stripHistoryIds(this.editable);
    }
    destroy() {
        this.collaborationStopBus && this.collaborationStopBus();
        if (this.peerToPeerLoading) {
            this.peerToPeerLoading.then(() => {
                this.stopPeerToPeer();
            });
        }
        super.destroy();
    }

    stopPeerToPeer() {
        this.joiningPtp = false;
        this.ptpJoined = false;
        this.resetCollabRequests();
        this.ptp && this.ptp.stop();
    }

    getCurrentCollaborativeSelection() {
        const selection = this.dependencies.selection.getEditableSelection();
        return {
            selection: this.dependencies.history.serializeSelection(selection),
            peerId: this.config.collaboration.peerId,
        };
    }
    setupCollaboration(collaborationChannel) {
        const modelName = collaborationChannel.collaborationModelName;
        const fieldName = collaborationChannel.collaborationFieldName;
        const resId = collaborationChannel.collaborationResId;
        const channelName = `editor_collaboration:${modelName}:${fieldName}:${resId}`;

        if (
            !(modelName && fieldName && resId)
        ) {
            return;
        }

        this.collaborationChannelName = channelName;
        this.historyStepsBuffer = [];

        const collaborationBusListener = (payload) => {
            if (
                payload.model_name === modelName &&
                payload.field_name === fieldName &&
                payload.res_id === resId
            ) {
                if (payload.notificationName === "html_field_write") {
                    this.onServerLastIdUpdate(payload.notificationPayload.last_step_id);
                } else if (this.ptpJoined) {
                    this.peerToPeerLoading.then(() =>
                        this.ptp.handleNotification(payload),
                    );
                }
            }
        };
        const { busService } = this.config.collaboration;
        busService.subscribe("editor_collaboration", collaborationBusListener);
        busService.addChannel(this.collaborationChannelName);
        this.collaborationStopBus = () => {
            busService.unsubscribe("editor_collaboration", collaborationBusListener);
            busService.deleteChannel(this.collaborationChannelName);
        };

        this.startCollaborationTime = new Date().getTime();



        const loadPeerToPeer = async () => {
            if (!ICE_SERVERS) {
                ICE_SERVERS = await rpc("/html_editor/get_ice_servers");
            }

            let iceServers = ICE_SERVERS;
            if (!iceServers.length) {
                iceServers = [
                    {
                        urls: [
                            "stun:stun1.l.google.com:19302",
                            "stun:stun2.l.google.com:19302",
                        ],
                    },
                ];
            }
            this.iceServers = iceServers;

            this.ptp = this.getNewPtp();
        };

        this.peerToPeerLoading = loadPeerToPeer();
    }

    getNewPtp() {
        const rpcMutex = new Mutex();
        const { collaborationChannel } = this.config.collaboration;
        const modelName = collaborationChannel.collaborationModelName;
        const fieldName = collaborationChannel.collaborationFieldName;
        const resId = collaborationChannel.collaborationResId;

        this.historySyncAtLeastOnce = false;

        return new PeerToPeer({
            peerConnectionConfig: { iceServers: this.iceServers },
            currentPeerId: this.config.collaboration.peerId,
            broadcastAll: (rpcData) =>
                rpcMutex.exec(async () =>
                    rpc("/html_editor/bus_broadcast", {
                        model_name: modelName,
                        field_name: fieldName,
                        res_id: resId,
                        bus_data: rpcData,
                    }),
                ),
            onRequest: {
                get_peer_metadata: this.getMetadata.bind(this),
                get_missing_steps: (params) =>
                    this.dependencies.collaboration.historyGetMissingSteps(
                        params.requestPayload,
                    ),
                get_history_from_snapshot: () => this.getHistorySnapshot(),
                get_collaborative_selection: () =>
                    this.getCurrentCollaborativeSelection(),
                recover_document: (params) => {
                    const { serverDocumentId, fromStepId } = params.requestPayload;
                    if (
                        !this.dependencies.collaboration
                            .getBranchIds()
                            .includes(serverDocumentId)
                    ) {
                        return;
                    }
                    return {
                        missingSteps:
                            this.dependencies.collaboration.historyGetMissingSteps({
                                fromStepId,
                            }),
                        snapshot: this.getHistorySnapshot(),
                    };
                },
            },
            onNotification: async (notification) => {
                this.dispatchTo("collaboration_notification_handlers", notification);
                let { fromPeerId, notificationName, notificationPayload } =
                    notification;
                switch (notificationName) {
                    case "ptp_remove":
                        break;
                    case "ptp_disconnect":
                        this.ptp.removePeer(fromPeerId);
                        break;
                    case "rtc_data_channel_open": {
                        fromPeerId = notificationPayload.connectionPeerId;
                        const metadata = await this.requestPeer(
                            fromPeerId,
                            "get_peer_metadata",
                            undefined,
                            { transport: "rtc" },
                        );
                        if (metadata === REQUEST_ERROR) {
                            return;
                        }

                        this.ptp.peersInfos[fromPeerId].metadata = metadata;

                        if (!this.historySyncAtLeastOnce) {
                            const localPeer = {
                                id: this.config.collaboration.peerId,
                                startTime: this.startCollaborationTime,
                            };
                            const remotePeer = {
                                id: fromPeerId,
                                startTime: metadata.startTime,
                            };
                            if (isPeerFirst(localPeer, remotePeer)) {
                                this.historySyncAtLeastOnce = true;
                                this.historySyncFinished = true;
                            } else {
                                this.resetCollabRequests();
                                const response = await this.resetFromPeer(
                                    fromPeerId,
                                    this.lastCollaborationResetId,
                                );
                                if (response === REQUEST_ERROR) {
                                    return;
                                }
                            }
                        } else {
                            this.ptp.notifyAllPeers(
                                "oe_history_step",
                                this.dependencies.history.getHistorySteps().at(-1),
                                { transport: "rtc" },
                            );
                            this.resetCollaborativeSelection(fromPeerId);
                        }
                        break;
                    }
                    case "oe_history_step":
                        if (this.historySyncFinished) {
                            this.dependencies.collaboration.onExternalHistorySteps([
                                notificationPayload,
                            ]);
                        } else {
                            this.historyStepsBuffer.push(notificationPayload);
                        }
                        break;
                    case "oe_history_set_selection": {
                        const peer = this.ptp.peersInfos[fromPeerId];
                        if (!peer) {
                            return;
                        }
                        const selection = notificationPayload;
                        this.onExternalMultiselectionUpdate(selection);
                        break;
                    }
                }
            },
        });
    }
    /**
     * @param {string} peerId
     */
    getPeerMetadata(peerId) {
        return this.ptp.peersInfos[peerId]?.metadata;
    }
    /**
     * @param {CollaborationSelection} selection
     */
    onExternalMultiselectionUpdate(selection) {
        this.dispatchTo("collaborative_selection_update_handlers", selection);
    }

    async requestPeer(peerId, requestName, requestPayload, params) {
        return this.ptp
            .requestPeer(peerId, requestName, requestPayload, params)
            .catch((e) => {
                if (e instanceof RequestError) {
                    return REQUEST_ERROR;
                } else {
                    throw e;
                }
            });
    }
    getMetadata() {
        const metadatas = {
            startTime: this.startCollaborationTime,
            peerName: user.name,
        };
        for (const cb of this.getResource("collaboration_peer_metadata_providers")) {
            Object.assign(metadatas, cb());
        }
        return metadatas;
    }
    onServerLastIdUpdate(last_step_id) {
        this.serverLastStepId = last_step_id;
        this.isDocumentStale = this.isLastDocumentStale();
        if (this.isDocumentStale && this.ptpJoined) {
            return this.recoverFromStaleDocument();
        } else if (this.isDocumentStale && this.joiningPtp) {
            this.resetCollabRequests();
            this.joinPeerToPeer();
        }
    }

    joinPeerToPeer() {
        this.editable.removeEventListener("focus", this.joinPeerToPeer);
        if (this.peerToPeerLoading) {
            return this.peerToPeerLoading.then(async () => {
                this.joiningPtp = true;
                if (this.isDocumentStale) {
                    const success = await this.resetFromServerAndResyncWithPeers();
                    if (!success) {
                        return;
                    }
                }
                this.ptp.notifyAllPeers("ptp_join");
                this.joiningPtp = false;
                this.ptpJoined = true;
            });
        }
    }
    isLastDocumentStale() {
        if (!this.serverLastStepId) {
            return false;
        }
        return !this.dependencies.collaboration
            .getBranchIds()
            .includes(this.serverLastStepId);
    }

    async recoverFromStaleDocument() {
        return new Promise((resolve) => {
            const resetCollabCount = this.lastCollaborationResetId;

            const allPeers = this.getPtpPeers().map((peer) => peer.id);

            if (allPeers.length === 0) {
                if (this.isDocumentStale) {
                    this.showConflictDialog();
                    resolve();
                    return this.resetFromServerAndResyncWithPeers();
                }
            }

            let hasRetrievalBudgetTimeout = false;
            const snapshots = [];
            let nbPendingResponses = allPeers.length;

            const success = () => {
                resolve();
                clearTimeout(timeout);
            };

            for (const peerId of allPeers) {
                this.requestPeer(
                    peerId,
                    "recover_document",
                    {
                        serverDocumentId: this.serverLastStepId,
                        fromStepId: this.dependencies.collaboration
                            .getBranchIds()
                            .at(-1),
                    },
                    { transport: "rtc" },
                ).then((response) => {
                    nbPendingResponses--;
                    if (
                        response === REQUEST_ERROR ||
                        resetCollabCount !== this.lastCollaborationResetId ||
                        hasRetrievalBudgetTimeout ||
                        !response ||
                        !this.isDocumentStale
                    ) {
                        if (nbPendingResponses <= 0) {
                            processSnapshots();
                        }
                        return;
                    }
                    this.processMissingSteps(response.missingSteps);
                    this.isDocumentStale = this.isLastDocumentStale();
                    snapshots.push(response.snapshot);
                    if (nbPendingResponses < 1) {
                        processSnapshots();
                    }
                });
            }

            const processSnapshots = async () => {
                this.isDocumentStale = this.isLastDocumentStale();
                if (!this.isDocumentStale) {
                    return success();
                }
                if (snapshots[0]) {
                    this.showConflictDialog();
                }
                for (const snapshot of snapshots) {
                    this.applySnapshot(snapshot);
                    this.isDocumentStale = this.isLastDocumentStale();
                    if (!this.isDocumentStale) {
                        return success();
                    }
                }

                if (this.isDocumentStale) {
                    this.showConflictDialog();
                    await this.resetFromServerAndResyncWithPeers();
                }

                success();
            };

            const timeout = setTimeout(() => {
                if (resetCollabCount !== this.lastCollaborationResetId) {
                    return;
                }
                hasRetrievalBudgetTimeout = true;
                this.onRecoveryPeerTimeout(processSnapshots);
            }, PTP_MAX_RECOVERY_TIME);
        });
    }

    getPtpPeers() {
        const peers = Object.entries(this.ptp.peersInfos).map(([peerId, peerInfo]) => ({
            id: peerId,
            ...peerInfo,
        }));
        return peers.sort((a, b) => (isPeerFirst(a, b) ? -1 : 1));
    }

    getLastHistoryStepId(value) {
        const matchId = value.match(/data-last-history-steps="[0-9,]*?([0-9]+)"/);
        return matchId && matchId[1];
    }

    resetCollabRequests() {
        this.lastCollaborationResetId++;
        this.ptp && this.ptp.abortCurrentRequests();
    }
    async resetFromServerAndResyncWithPeers() {
        let collaborationResetId = this.lastCollaborationResetId;
        const record = await this.getCurrentRecord();
        if (collaborationResetId !== this.lastCollaborationResetId) {
            return;
        }

        const content =
            record[
                this.config.collaboration.collaborationChannel.collaborationFieldName
            ];
        const lastHistoryId = content && this.getLastHistoryStepId(content);
        if (this.serverLastStepId !== lastHistoryId) {
            throw new Error(
                "Concurency detected while recovering from a stale document. The last history id of the server is different from the history id received by the html_field_write event.",
            );
        }

        this.isDocumentStale = false;
        if (content) {
            this.editable.innerHTML = content;
        } else {
            this.editable.replaceChildren(
                this.dependencies.baseContainer.createBaseContainer(),
            );
        }
        stripHistoryIds(this.editable);
        this.dispatchTo("normalize_handlers", this.editable);

        this.dependencies.history.reset(content);

        this.historySyncAtLeastOnce = false;
        this.resetCollabRequests();
        collaborationResetId = this.lastCollaborationResetId;
        this.startCollaborationTime = new Date().getTime();
        await Promise.all(
            this.getPtpPeers().map((peer) =>
                this.resetFromPeer(peer.id, collaborationResetId),
            ),
        );
        return true;
    }
    onReset(content) {
        this.historyShareId = generateId();

        const lastStepId =
            content && content.match(/data-last-history-steps="([\d,]+)"/)?.[1];
        if (lastStepId) {
            this.dependencies.collaboration.setInitialBranchStepId(lastStepId);
        }
    }

    /**
     * @private
     * @param {Array<Object>|-1} missingSteps
     * @return {Promise<boolean>}
     */
    async processMissingSteps(missingSteps) {
        if (missingSteps === -1 || !missingSteps.length) {
            return false;
        }
        this.dependencies.collaboration.onExternalHistorySteps(missingSteps);
        return true;
    }
    applySnapshot(snapshot) {
        const { steps, historyIds, historyShareId } = snapshot;
        const isStaleDocument =
            this.serverLastStepId && !historyIds.includes(this.serverLastStepId);
        if (isStaleDocument) {
            return;
        }
        this.historyShareId = historyShareId;
        this.historySyncAtLeastOnce = true;
        this.dependencies.collaboration.resetFromSteps(steps, historyIds);

        return true;
    }

    /**
     * @param {Function} processSnapshots
     */
    async onRecoveryPeerTimeout(processSnapshots) {
        processSnapshots();
    }
    showConflictDialog() {
        // todo: implement conflict dialog
        // if (this.conflictDialogOpened) {
        //     return;
        // }
        // const content = markup(this.odooEditor.editable.cloneNode(true).outerHTML);
        // this.conflictDialogOpened = true;
        // this.env.services.dialog.add(ConflictDialog, {
        //     content,
        //     close: () => (this.conflictDialogOpened = false),
        // });
    }

    getHistorySnapshot() {
        return Object.assign({}, this.dependencies.collaboration.getSnapshotSteps(), {
            historyShareId: this.historyShareId,
        });
    }

    async resetFromPeer(fromPeerId, resetCollabCount) {
        this.historySyncFinished = false;
        this.historyStepsBuffer = [];
        const snapshot = await this.requestPeer(
            fromPeerId,
            "get_history_from_snapshot",
            undefined,
            { transport: "rtc" },
        );
        if (snapshot === REQUEST_ERROR) {
            return REQUEST_ERROR;
        }
        if (resetCollabCount !== this.lastCollaborationResetId) {
            return;
        }
        if (this.historySyncAtLeastOnce) {
            return;
        }
        const selection = this.dependencies.selection.getEditableSelection();
        let anchorNodeIndexPath = this._getNodeIndexPath(selection.anchorNode);
        let anchorOffset = selection.anchorOffset;
        if (selection.anchorNode === this.editable) {
            anchorNodeIndexPath = this._getNodeIndexPath(this.editable.firstChild);
            anchorOffset = 0;
        }
        const applied = this.applySnapshot(snapshot);
        if (!applied) {
            return;
        }
        const anchorNode = this._getNodeFromIndexPath(anchorNodeIndexPath);
        if (
            this.dependencies.selection.isSelectionInEditable({
                anchorNode,
                focusNode: anchorNode,
            })
        ) {
            this.dependencies.selection.setSelection({
                anchorNode,
                anchorOffset,
            });
        }
        this.historySyncFinished = true;
        if (this.historyStepsBuffer.length) {
            this.dependencies.collaboration.onExternalHistorySteps(
                this.historyStepsBuffer,
            );
            this.historyStepsBuffer = [];
        }
        this.editable.dispatchEvent(new CustomEvent("onHistoryResetFromPeer"));
        this.resetCollaborativeSelection(fromPeerId);
    }

    async resetCollaborativeSelection(fromPeerId) {
        const remoteSelection = await this.requestPeer(
            fromPeerId,
            "get_collaborative_selection",
            undefined,
            { transport: "rtc" },
        );
        if (remoteSelection === REQUEST_ERROR) {
            return;
        }
        if (remoteSelection) {
            this.onExternalMultiselectionUpdate(remoteSelection);
        }
    }
    async onHistoryMissingParentStep({ step, fromStepId }) {
        if (!this.ptp) {
            return;
        }
        const missingSteps = await this.requestPeer(
            step.peerId,
            "get_missing_steps",
            {
                fromStepId: fromStepId,
                toStepId: step.id,
            },
            { transport: "rtc" },
        );
        if (missingSteps === REQUEST_ERROR) {
            return;
        }
        this.processMissingSteps(
            Array.isArray(missingSteps) ? missingSteps.concat(step) : missingSteps,
        );
    }
    async getCurrentRecord() {
        const [record] = await this.config.collaboration.ormService.read(
            this.config.collaboration.collaborationChannel.collaborationModelName,
            [this.config.collaboration.collaborationChannel.collaborationResId],
            [this.config.collaboration.collaborationChannel.collaborationFieldName],
        );
        return record;
    }
    attachHistoryIds(editable) {
        const historyIds = this.dependencies.collaboration.getBranchIds().join(",");
        const firstChild = editable.children[0];
        if (firstChild) {
            firstChild.setAttribute("data-last-history-steps", historyIds);
        }
    }

    /**
     * @param {Node} node
     * @returns {number[]}
     */
    _getNodeIndexPath(node) {
        return [node, ...ancestors(node, this.editable)].map((ancestor) =>
            childNodeIndex(ancestor),
        );
    }
    /**
     * @param {number[]} indexPath
     * @returns {Node|undefined}
     */
    _getNodeFromIndexPath(indexPath) {
        return indexPath.reduceRight(
            (node, index) => node?.childNodes?.[index],
            this.editable.parentElement,
        );
    }
}

function isPeerFirst(peerA, peerB) {
    if (peerA.startTime === peerB.startTime) {
        return compareIds(peerA.id, peerB.id) < 0;
    }
    if (peerA.startTime === undefined || peerB.startTime === undefined) {
        return Boolean(peerA.startTime);
    } else {
        return peerA.startTime < peerB.startTime;
    }
}

export function stripHistoryIds(element) {
    element
        .querySelectorAll("[data-last-history-steps]")
        .forEach((el) => el.removeAttribute("data-last-history-steps"));
}
