// @ts-check
/** @odoo-module native */
import { ScheduledMessage } from "@mail/chatter/web/scheduled_message";
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { AttachmentList } from "@mail/core/common/attachment_list";
import { useAttachmentUploader } from "@mail/core/common/attachment_uploader_hook";
import { usePopoutAttachment } from "@mail/core/common/attachment_view";
import { MailAttachmentDropzone } from "@mail/core/common/mail_attachment_dropzone";
import { useMessageSearch } from "@mail/core/common/message_search_hook";
import { SearchMessageInput } from "@mail/core/common/search_message_input";
import { SearchMessageResult } from "@mail/core/common/search_message_result";
import { Activity } from "@mail/core/web/activity";
import { FollowerList } from "@mail/core/web/follower_list";
import { RecipientsInput } from "@mail/core/web/recipients_input";
import { useHover, useMessageScrolling } from "@mail/utils/common/hooks";
import {
    readLocalStorageItem,
    setLocalStorageItem,
} from "@mail/utils/common/local_storage";
import { assignGetter, isDragSourceExternalFile } from "@mail/utils/common/misc";
import { status, useEffect } from "@odoo/owl";
import { Dropdown, useDropdownState } from "@web/components/dropdown";
import { useCustomDropzone } from "@web/components/dropzone";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { FileUploader } from "@web/core/file_upload";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { KeepLast } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { useRecordObserver } from "@web/fields/hooks/record_observer";

const log = makeLogger("mail.chatter");
const CHATTER_ASIDE_COLLAPSED_LS = "chatter_aside_collapsed";
export const DELAY_FOR_SPINNER = 1000;

/** @typedef {import("@mail/chatter/web_portal/chatter").Props & { close?: function, compactHeight?: boolean, has_activities?: boolean, hasAttachmentPreview?: boolean, hasParentReloadOnActivityChanged?: boolean, hasParentReloadOnAttachmentsChanged?: boolean, hasParentReloadOnFollowersUpdate?: boolean, hasParentReloadOnMessagePosted?: boolean, highlightMessageId?: number, isAttachmentBoxVisibleInitially?: boolean, isChatterAside?: boolean, isInFormSheetBg?: boolean, saveRecord?: function, record?: Object, }} Props */
/** @typedef {import("@mail/chatter/web_portal/chatter").State & { composerType: "message"|"note"|false, isAttachmentBoxOpened: boolean, isSearchOpen: boolean, showActivities: boolean, showAttachmentLoading: boolean, showScheduledMessages: boolean, }} State */
/** @extends {Chatter<Props, State>} */
export class WebChatter extends Chatter {
    static template = "mail.Chatter";
    static components = {
        ...Chatter.components,
        Activity,
        AttachmentList,
        Dropdown,
        FileUploader,
        FollowerList,
        RecipientsInput,
        ScheduledMessage,
        SearchMessageInput,
        SearchMessageResult,
    };
    static props = [
        ...Chatter.props,
        "close?",
        "compactHeight?",
        "has_activities?",
        "hasAttachmentPreview?",
        "hasParentReloadOnActivityChanged?",
        "hasParentReloadOnAttachmentsChanged?",
        "hasParentReloadOnFollowersUpdate?",
        "hasParentReloadOnMessagePosted?",
        "highlightMessageId?",
        "isAttachmentBoxVisibleInitially?",
        "isChatterAside?",
        "isInFormSheetBg?",
        "saveRecord?",
        "record?",
    ];
    static defaultProps = {
        ...Chatter.defaultProps,
        compactHeight: false,
        has_activities: true,
        hasAttachmentPreview: false,
        hasParentReloadOnActivityChanged: false,
        hasParentReloadOnAttachmentsChanged: false,
        hasParentReloadOnFollowersUpdate: false,
        hasParentReloadOnMessagePosted: false,
        isAttachmentBoxVisibleInitially: false,
        isChatterAside: false,
        isInFormSheetBg: true,
    };

    _setupServicesAndState() {
        this.orm = useService("orm");
        this.keepLastSuggestedRecipientsUpdate = new KeepLast();
        this.mailImpactingFields = { recordFields: [], emailFields: [] };
        useRecordObserver(
            /** @param {import("@web/model/relational_model/record").RelationalRecord} record */ (
                record,
            ) => this.updateRecipients(record),
        );
        this.attachmentPopout = usePopoutAttachment();
        Object.assign(this.state, {
            composerType: false,
            isAttachmentBoxOpened: this.props.isAttachmentBoxVisibleInitially,
            isSearchOpen: false,
            showActivities: true,
            showAttachmentLoading: false,
            showScheduledMessages: true,
        });
        this.messageSearch = useMessageSearch();
        this.attachmentUploader = useAttachmentUploader(
            this.store.Thread.insert({
                model: this.props.threadModel,
                id: this.props.threadId,
            }),
        );
        this.unfollowHover = useHover("unfollow");
        this.followerListDropdown = useDropdownState();
        /** @type {number|null} */
        this.loadingAttachmentTimeout = null;
        /** @type {Map<string, Function>} */
        this.uploadHandlers = new Map();
    }
    _setupChatterDropzone() {
        useCustomDropzone(
            this.rootRef,
            MailAttachmentDropzone,
            {
                extraClass: "o-mail-Chatter-dropzone",
                /** @param {Event} ev */
                onDrop: async (ev) => {
                    if (this.state.composerType) {
                        return;
                    }
                    if (
                        isDragSourceExternalFile(
                            /** @type {DragEvent} */ (ev).dataTransfer,
                        )
                    ) {
                        const files = [
                            .../** @type {DragEvent} */ (ev).dataTransfer.files,
                        ];
                        if (!this.state.thread.id) {
                            const saved = await this.props.saveRecord?.();
                            if (!saved) {
                                return;
                            }
                        }
                        const thread = this.state.thread.id
                            ? this.state.thread
                            : this.store.Thread.insert({
                                  model: this.props.threadModel,
                                  id: this.props.record.resId,
                              });
                        Promise.all(
                            files.map((file) =>
                                this.attachmentUploader.uploadFile(file, { thread }),
                            ),
                        ).then(() => {
                            if (this.props.hasParentReloadOnAttachmentsChanged) {
                                this.reloadParentView();
                            }
                        });
                        this.state.isAttachmentBoxOpened = true;
                    }
                },
            },
            () =>
                (!this.store.meetingViewOpened || this.env.inMeetingView) &&
                (this.state.thread?.isTransient || this.state.thread?.canPostMessage),
        );
    }
    _setupChatterEffects() {
        useEffect(
            () => {
                if (!this.state.thread) {
                    return;
                }
                browser.clearTimeout(this.loadingAttachmentTimeout);
                if (this.state.thread?.isLoadingAttachments) {
                    this.loadingAttachmentTimeout = browser.setTimeout(
                        () => (this.state.showAttachmentLoading = true),
                        DELAY_FOR_SPINNER,
                    );
                } else {
                    this.state.showAttachmentLoading = false;
                    this.state.isAttachmentBoxOpened =
                        this.state.isAttachmentBoxOpened ||
                        (this.props.isAttachmentBoxVisibleInitially &&
                            this.attachments.length > 0);
                }
                return () => browser.clearTimeout(this.loadingAttachmentTimeout);
            },
            () => [this.state.thread, this.state.thread?.isLoadingAttachments],
        );
        useEffect(
            () => {
                if (
                    this.state.thread &&
                    !["new", "loading"].includes(this.state.thread.status) &&
                    this.attachments.length === 0
                ) {
                    this.state.isAttachmentBoxOpened = false;
                }
            },
            () => [this.state.thread?.status, this.attachments.length],
        );
        useEffect(
            () => {
                this.state.aside = this.props.isChatterAside;
            },
            () => [this.props.isChatterAside],
        );
    }
    setup() {
        this.messageHighlight = useMessageScrolling();
        super.setup();
        this._setupServicesAndState();
        this._setupChatterDropzone();
        this._setupChatterEffects();
    }

    /**
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     * @param {"message"|"note"|false} [mode=this.state.composerType]
     */
    async updateRecipients(record, mode = this.state.composerType) {
        if (!record) {
            return;
        }
        // subscribe the record observer: to every field until the thread tells which
        // fields matter for recipients, then to those only
        const watchedFields = [
            ...this.mailImpactingFields.recordFields,
            ...this.mailImpactingFields.emailFields,
        ];
        for (const field of watchedFields.length
            ? watchedFields
            : Object.keys(record.data)) {
            void record.data[field];
        }
        const partnerIds = [];
        let email;
        this.mailImpactingFields.recordFields.forEach((field) => {
            const value = record.changes[field];
            if (record.data[field] !== undefined && value) {
                partnerIds.push(value.id);
            }
        });
        this.mailImpactingFields.emailFields.forEach((field) => {
            const value = record.changes[field];
            if (record.data[field] !== undefined && value) {
                email = value;
                return;
            }
        });
        if (
            (!partnerIds.length && !email) ||
            mode !== "message" ||
            status(this) === "destroyed"
        ) {
            return;
        }
        const thread = this.state.thread;
        const queryKey = JSON.stringify({
            threadId: thread?.localId,
            partnerIds: [...partnerIds].sort((a, b) => a - b),
            email: email || null,
        });
        if (queryKey === this._lastRecipientsQueryKey) {
            log.logic("updateRecipients dedup", () => ({ queryKey }));
            return;
        }
        const endRecipients = log.perf("suggested recipients");
        const recipients = await this.keepLastSuggestedRecipientsUpdate.add(
            rpc("/mail/thread/recipients/get_suggested_recipients", {
                thread_model: this.props.threadModel,
                thread_id: this.props.threadId,
                partner_ids: partnerIds,
                main_email: email,
            }),
        );
        endRecipients({ thread: thread?.localId, recipients: recipients?.length });
        if (status(this) === "destroyed" || !this.state.thread?.eq(thread)) {
            log.logic("updateRecipients result dropped", () => ({
                thread: thread?.localId,
                current: this.state.thread?.localId,
                destroyed: status(this) === "destroyed",
            }));
            return;
        }
        this._lastRecipientsQueryKey = queryKey;
        this.state.thread.suggestedRecipients = recipients.map((result) => ({
            display_name: result.display_name,
            email: result.email,
            partner_id: result.partner_id,
            name: result.name || result.email,
        }));
        this.state.thread.additionalRecipients =
            this.state.thread.additionalRecipients.filter((additionalRecipient) =>
                this.state.thread.suggestedRecipients.every(
                    (suggestedRecipient) =>
                        suggestedRecipient.partner_id !==
                        additionalRecipient.partner_id,
                ),
            );
    }

    /** @returns {import("models").Activity[]} */
    get activities() {
        return this.state.thread?.activities ?? [];
    }

    get afterPostRequestList() {
        return [
            ...super.afterPostRequestList,
            "followers",
            "scheduledMessages",
            "suggestedRecipients",
        ];
    }

    get attachments() {
        return this.state.thread?.attachments ?? [];
    }

    get childSubEnv() {
        const res = Object.assign(super.childSubEnv, {
            messageHighlight: this.messageHighlight,
        });
        assignGetter(res.inChatter, { aside: () => this.props.isChatterAside });
        Object.assign(res.inChatter, {
            toggleComposer: this.toggleComposer.bind(this),
        });
        return res;
    }

    get followerButtonLabel() {
        return _t("Show Followers");
    }

    get followingText() {
        return _t("Following");
    }

    get isCollapsedAside() {
        return (
            this.props.isChatterAside &&
            readLocalStorageItem(this.store, CHATTER_ASIDE_COLLAPSED_LS) === "true"
        );
    }

    /** @returns {boolean} */
    get isDisabled() {
        return !this.state.thread.id || !this.state.thread?.hasReadAccess;
    }

    get onCloseFullComposerRequestList() {
        return [...super.onCloseFullComposerRequestList, "scheduledMessages"];
    }

    get requestList() {
        return [
            ...super.requestList,
            "activities",
            "attachments",
            "contact_fields",
            "followers",
            "scheduledMessages",
            "suggestedRecipients",
        ];
    }

    get scheduledMessages() {
        return this.state.thread?.scheduledMessages ?? [];
    }

    get unfollowText() {
        return _t("Unfollow");
    }

    /**
     * @param {string} threadModel
     * @param {number|false} threadId
     */
    changeThread(threadModel, threadId) {
        super.changeThread(threadModel, threadId);
        this.attachmentUploader.thread = this.state.thread;
        if (threadId === false) {
            this.state.composerType = false;
            this.closeSearch();
        } else {
            if (this.onThreadCreated) {
                log.lifecycle("onThreadCreated callback", () => ({
                    thread: this.state.thread.localId,
                }));
            }
            this.onThreadCreated?.(this.state.thread);
            this.onThreadCreated = null;
            this.messageSearch.thread = this.state.thread;
            this.closeSearch();
        }
    }

    closeSearch() {
        this.messageSearch.clear();
        this.state.isSearchOpen = false;
    }

    /**
     * @param {import("models").Thread} thread
     * @param {string[]} requestList
     */
    async load(thread, requestList) {
        await super.load(thread, requestList);
        if (!thread.id || !this.state.thread?.eq(thread)) {
            return;
        }
        this.mailImpactingFields = {
            emailFields: this.state.thread.primary_email_field
                ? [this.state.thread.primary_email_field]
                : [],
            recordFields: this.state.thread.partner_fields || [],
        };
        this._lastRecipientsQueryKey = undefined;
        this.updateRecipients(this.props.record);
    }

    /** @param {import("models").Thread} thread */
    onActivityChanged(thread) {
        log.logic("onActivityChanged", () => ({
            thread: thread.localId,
            parentReload: this.props.hasParentReloadOnActivityChanged,
        }));
        this.load(thread, [...this.requestList, "messages"]);
        if (this.props.hasParentReloadOnActivityChanged) {
            this.reloadParentView();
        }
    }

    onAddFollowers() {
        log.logic("onAddFollowers", () => ({ thread: this.state.thread?.localId }));
        this.load(this.state.thread, ["followers", "suggestedRecipients"]);
        if (this.props.hasParentReloadOnFollowersUpdate) {
            this.reloadParentView();
        }
    }

    onClickAddAttachments() {
        if (this.attachments.length === 0) {
            return;
        }
        this.state.isAttachmentBoxOpened = !this.state.isAttachmentBoxOpened;
        if (this.state.isAttachmentBoxOpened) {
            this.rootRef.el.scrollTop = 0;
            this.state.thread.scrollTop = "bottom";
        }
    }

    /** @param {MouseEvent} ev */
    async onClickAttachFile(ev) {
        if (this.state.thread.id) {
            return;
        }
        const saved = await this.props.saveRecord?.();
        if (!saved) {
            return false;
        }
    }

    onClickSearch() {
        log.logic("onClickSearch", () => ({ open: !this.state.isSearchOpen }));
        this.state.composerType = false;
        this.state.isSearchOpen = !this.state.isSearchOpen;
    }

    /** @param {boolean} isDiscard */
    onCloseFullComposerCallback(isDiscard) {
        this.toggleComposer();
        super.onCloseFullComposerCallback();
        if (!isDiscard) {
            this.reloadParentView();
        }
    }

    onFollowerChanged() {
        this.reloadParentView();
    }

    _onMounted() {
        super._onMounted();
        if (this.state.thread && this.props.highlightMessageId) {
            this.state.thread.highlightMessage = this.store["mail.message"].insert({
                id: this.props.highlightMessageId,
            });
        }
    }

    onPostCallback() {
        log.logic("onPostCallback", () => ({
            thread: this.state.thread?.localId,
            parentReload: this.props.hasParentReloadOnMessagePosted,
        }));
        if (this.props.hasParentReloadOnMessagePosted) {
            this.reloadParentView();
        }
        this.toggleComposer();
        super.onPostCallback();
    }

    /** @param {import("models").Thread} thread */
    onScheduledMessageChanged(thread) {
        this.load(thread, ["scheduledMessages", "messages"]);
        this.reloadParentView();
    }

    /** @param {import("models").Thread} thread */
    onSuggestedRecipientAdded(thread) {
        this.load(thread, ["suggestedRecipients"]);
    }

    /**
     * @param {Parameters<ReturnType<import("@mail/core/common/attachment_uploader_hook").useAttachmentUploader>["uploadData"]>[0]} data
     * @param {{thread?: import("models").Thread}} [options]
     */
    onUploaded(data, { thread } = {}) {
        const threadLocalId = thread.localId;
        if (!this.uploadHandlers.has(threadLocalId)) {
            const self = this;
            this.uploadHandlers.set(
                threadLocalId,
                /** @param {{data: string, name: string, type: string}} data */
                async function handleUpload(data) {
                    try {
                        const uploadThread =
                            thread.id || !self.props.record.resId
                                ? thread
                                : self.store.Thread.insert({
                                      model: self.props.threadModel,
                                      id: self.props.record.resId,
                                  });
                        log.logic("handleUpload", () => ({
                            uploadThread: uploadThread.localId,
                            current: self.state.thread?.localId,
                            name: data.name,
                        }));
                        await self.attachmentUploader.uploadData(data, {
                            thread: uploadThread,
                        });
                        if (!uploadThread.eq(self.state.thread)) {
                            log.logic("handleUpload thread changed during upload");
                            return;
                        }
                        if (self.props.hasParentReloadOnAttachmentsChanged) {
                            self.reloadParentView();
                        }
                        self.state.isAttachmentBoxOpened = true;
                        if (self.rootRef.el) {
                            self.rootRef.el.scrollTop = 0;
                        }
                        self.state.thread.scrollTop = "bottom";
                    } finally {
                        self.uploadHandlers.delete(threadLocalId);
                    }
                },
            );
        }
        return this.uploadHandlers.get(threadLocalId);
    }

    async reloadParentView() {
        const endReload = log.perf("reloadParentView");
        const saved = await this.props.saveRecord?.();
        if (saved === false) {
            endReload({ saved: false });
            return;
        }
        if (this.props.record) {
            await this.props.record.load();
        }
        endReload({ thread: this.state.thread?.localId });
    }

    async scheduleActivity() {
        log.logic("scheduleActivity", () => ({
            thread: this.state.thread?.localId,
            persisted: Boolean(this.state.thread.id),
        }));
        this.closeSearch();
        /** @param {import("models").Thread} thread */
        const schedule = async (thread) => {
            await this.store.scheduleActivity(thread.model, [thread.id]);
            this.load(thread, ["activities", "messages"]);
            if (this.props.hasParentReloadOnActivityChanged) {
                await this.reloadParentView();
            }
        };
        if (this.state.thread.id) {
            schedule(this.state.thread);
        } else {
            this.onThreadCreated = schedule;
            const saved = await this.props.saveRecord?.();
            if (!saved) {
                this.onThreadCreated = null;
            }
        }
    }

    toggleActivities() {
        this.state.showActivities = !this.state.showActivities;
    }

    toggleChatterCollapse() {
        const collapsed = !this.isCollapsedAside;
        log.logic("toggleChatterCollapse", () => ({ collapsed }));
        setLocalStorageItem(this.store, CHATTER_ASIDE_COLLAPSED_LS, String(collapsed));
    }

    /**
     * @param {"message"|"note"|false} [mode=false]
     * @param {Object} [options]
     * @param {boolean} [options.force=false]
     */
    async toggleComposer(mode = false, { force = false } = {}) {
        log.logic("toggleComposer", () => ({
            thread: this.state.thread?.localId,
            from: this.state.composerType,
            mode,
            force,
            persisted: Boolean(this.state.thread.id),
        }));
        this.closeSearch();
        const toggle = () => {
            if (!force && this.state.composerType === mode) {
                this.state.composerType = false;
            } else {
                this.state.composerType = mode;
                if (mode === "message") {
                    this.updateRecipients(this.props.record, mode);
                }
            }
        };
        if (this.state.thread.id) {
            toggle();
        } else {
            this.onThreadCreated = toggle;
            const saved = await this.props.saveRecord?.();
            if (!saved) {
                this.onThreadCreated = null;
            }
        }
    }

    toggleScheduledMessages() {
        this.state.showScheduledMessages = !this.state.showScheduledMessages;
    }

    /** @param {import("models").Attachment} attachment */
    async unlinkAttachment(attachment) {
        log.logic("unlinkAttachment", () => ({ attachmentId: attachment.id }));
        await this.attachmentUploader.unlink(attachment);
        if (this.props.hasParentReloadOnAttachmentsChanged) {
            this.reloadParentView();
        }
    }

    popoutAttachment() {
        this.attachmentPopout.popout();
    }
}
