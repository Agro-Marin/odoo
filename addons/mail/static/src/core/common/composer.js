/** @odoo-module native */
import { closestElement, lastLeaf } from "@html_editor/utils/dom_traversal";
import { rightPos } from "@html_editor/utils/position";
import { Wysiwyg } from "@html_editor/wysiwyg";
import { ActionList } from "@mail/core/common/action_list";
import { AttachmentList } from "@mail/core/common/attachment_list";
import { useAttachmentUploader } from "@mail/core/common/attachment_uploader_hook";
import { useComposerActions } from "@mail/core/common/composer_actions";
import {
    clearComposerDraft,
    restoreComposerDraft,
    saveComposerDraft,
    useComposerDraft,
} from "@mail/core/common/composer_draft";
import { useFullComposer } from "@mail/core/common/full_composer_hook";
import { MailAttachmentDropzone } from "@mail/core/common/mail_attachment_dropzone";
import { MessageConfirmDialog } from "@mail/core/common/message_confirm_dialog";
import { NavigableList } from "@mail/core/common/navigable_list";
import {
    MAIL_PLUGINS,
    MAIL_SMALL_UI_PLUGINS,
} from "@mail/core/common/plugin/plugin_sets";
import {
    mapSuggestionsToOptions,
    useSuggestion,
} from "@mail/core/common/suggestion_hook";
import { insertAtSelection } from "@mail/utils/common/composer_insert";
import { trimEmptyBlocksAround } from "@mail/utils/common/format";
import { useSelection } from "@mail/utils/common/hooks";
import { isDragSourceExternalFile } from "@mail/utils/common/misc";
import { markThreadAsReadIfAtBottom } from "@mail/utils/common/thread_read";
import {
    Component,
    markup,
    onMounted,
    onWillUnmount,
    reactive,
    status,
    toRaw,
    useChildSubEnv,
    useEffect,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { useCustomDropzone } from "@web/components/dropzone/dropzone_hook";
import { browser } from "@web/core/browser/browser";
import {
    isDisplayStandalone,
    isIOS,
    isMobileOS,
} from "@web/core/browser/feature_detection";
import { FileUploader } from "@web/core/file_upload/file_handler";
import { _t } from "@web/core/l10n/translation";
import { isEventHandled, markEventHandled } from "@web/core/utils/dom/events";
import { htmlJoin, isHtmlEmpty, setElementContent } from "@web/core/utils/dom/html";
import { isEmail } from "@web/core/utils/format/strings";
import { useService } from "@web/core/utils/hooks";
const EDIT_CLICK_TYPE = {
    CANCEL: "cancel",
    SAVE: "save",
};

/**
 * @typedef {Object} Props
 * @property {import("models").Composer} composer
 * @property {'compact'|'normal'|'extended'} [mode] default: 'normal'
 * @property {'message'|'note'|false} [type] default: false
 * @property {string} [placeholder]
 * @property {string} [className]
 * @property {function} [onDiscardCallback]
 * @property {function} [onPostCallback]
 * @property {number} [autofocus]
 * @property {import("@web/core/utils/hooks").Ref} [dropzoneRef]
 * @extends {Component<Props, Env>}
 */
export class Composer extends Component {
    static components = {
        ActionList,
        AttachmentList,
        Dropdown,
        DropdownItem,
        FileUploader,
        NavigableList,
        Wysiwyg,
    };
    static defaultProps = {
        autofocus: 0,
        mode: "normal",
        className: "",
        sidebar: true,
        showFullComposer: true,
        allowUpload: true,
    };
    static props = [
        "composer",
        "autofocus?",
        "onCloseFullComposerCallback?",
        "onDiscardCallback?",
        "onPostCallback?",
        "mode?",
        "placeholder?",
        "dropzoneRef?",
        "className?",
        "sidebar?",
        "type?",
        "showFullComposer?",
        "allowUpload?",
    ];
    static template = "mail.Composer";

    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        /** @type {import("@html_editor/editor").Editor} */
        this.editor = undefined;
        this.isMobileOS = isMobileOS();
        this.isIosPwa = isIOS() && isDisplayStandalone();
        this.store = useService("mail.store");
        this.composerActions = useComposerActions({
            composer: () => this.props.composer,
        });
        this.EDIT_CLICK_TYPE = EDIT_CLICK_TYPE;
        this.OR_PRESS_SEND_KEYBIND = _t("or press %(send_keybind)s", {
            send_keybind: htmlJoin(
                this.sendKeybinds.map((key) => markup`<samp>${key}</samp>`),
                " + ",
            ),
        });
        this.attachmentUploader = useAttachmentUploader(
            this.thread ?? this.props.composer.message.thread,
            { composer: this.props.composer },
        );
        this.ui = useService("ui");
        this.composerService = useService("mail.composer");
        this.ref = useRef("textarea");
        this.fakeTextarea = useRef("fakeTextarea");
        this.inputContainerRef = useRef("input-container");
        this.pickerContainerRef = useRef("picker-container");
        this.state = useState({
            active: true,
        });
        this.root = useRef("root");
        this.fullComposer = useFullComposer();
        this.draft = useComposerDraft();
        this.selection = useSelection({
            refName: "textarea",
            model: this.props.composer.selection,
            preserveOnClickAwayPredicate: async (ev) => {
                // Let event be handled by bubbling handlers first. Routed
                // through `browser` so tests can mock time.
                await new Promise((resolve) => browser.setTimeout(resolve));
                return (
                    !this.isEventTrusted(ev) ||
                    isEventHandled(ev, "sidebar.openThread") ||
                    isEventHandled(ev, "emoji.selectEmoji") ||
                    isEventHandled(ev, "Composer.onClickAddEmoji") ||
                    isEventHandled(ev, "composer.clickOnAddAttachment") ||
                    isEventHandled(ev, "composer.selectSuggestion") ||
                    isEventHandled(ev, "composer.clickInsertCannedResponse")
                );
            },
        });
        this.suggestion = useSuggestion();
        this.markEventHandled = markEventHandled;
        this.onDropFile = this.onDropFile.bind(this);
        this.updateFromEditor = false;
        useExternalListener(
            window,
            "click",
            (ev) => {
                const target = ev.composedPath()[0];
                if (
                    this.ui.isSmall &&
                    this.composerActions.activePicker &&
                    this.pickerContainerRef.el &&
                    target !== this.pickerContainerRef.el &&
                    !this.pickerContainerRef.el.contains(target)
                ) {
                    this.composerActions.activePicker.close?.();
                }
            },
            { capture: true },
        );
        if (this.props.dropzoneRef) {
            useCustomDropzone(
                this.props.dropzoneRef,
                MailAttachmentDropzone,
                {
                    extraClass: "o-mail-Composer-dropzone",
                    onDrop: this.onDropFile,
                },
                () =>
                    this.props.allowUpload &&
                    (!this.store.rtc.state.isFullscreen || this.env.inMeetingView),
            );
        }
        useChildSubEnv({ inComposer: true });
        useEffect(
            (focus) => {
                if (focus && this.ref.el) {
                    this.selection.restore();
                    this.ref.el.focus();
                }
                if (focus && this.editor) {
                    this.editor.shared.selection.focusEditable();
                    this.editor.shared.selection.selectAroundNonEditable();
                }
            },
            () => [
                this.props.autofocus + this.props.composer.autofocus,
                this.props.placeholder,
            ],
        );
        useEffect(
            () => {
                if (this.props.composer.replyToMessage) {
                    this.props.composer.autofocus++;
                }
            },
            () => [this.props.composer.replyToMessage],
        );
        useEffect(
            () => {
                if (this.fakeTextarea.el?.scrollHeight) {
                    let wasEmpty = false;
                    if (!this.fakeTextarea.el.value) {
                        wasEmpty = true;
                        this.fakeTextarea.el.value = "0";
                    }
                    this.ref.el.style.height = this.fakeTextarea.el.scrollHeight + "px";
                    if (wasEmpty) {
                        this.fakeTextarea.el.value = "";
                    }
                }
            },
            () => [this.props.composer.composerText, this.ref.el],
        );
        useEffect(
            () => {
                if (!this.props.composer.forceCursorMove) {
                    return;
                }
                this.selection.restore();
                this.props.composer.forceCursorMove = false;
            },
            () => [this.props.composer.forceCursorMove],
        );
        onMounted(() => {
            this.ref.el?.scrollTo({ top: 0, behavior: "instant" });
        });
        onWillUnmount(() => {
            this.props.composer.isFocused = false;
            // drop the editor reference so the reactive callback below (bound
            // to the persistent composer record, which outlives this
            // component) can never write into a destroyed editor.
            this.editor = undefined;
        });
        const composerProxy = reactive(this.props.composer, () => {
            // `this.status` does not exist on an OWL component (status lives on
            // __owl__); the guard was always false, so the callback re-read
            // composerHtml and re-subscribed on every mount, leaking a
            // subscription per Composer mount. Use the public status() helper
            // and stop observing once destroyed.
            if (status(this) === "destroyed") {
                return;
            }
            const composerHtml = composerProxy.composerHtml;
            if (this.updateFromEditor) {
                return;
            }
            if (!this.editor?.editable) {
                return;
            }
            setElementContent(this.editor.editable, composerHtml);
            this.setEditorCursorEnd();
            this.editor.shared.history.addStep();
        });
        void composerProxy.composerHtml; // start observing
    }

    setEditorCursorEnd() {
        const lastNode = lastLeaf(this.editor?.editable);
        if (!lastNode) {
            return;
        }
        const nonEditableAncestor = closestElement(
            lastNode,
            (el) => !el.isContentEditable,
        );
        if (nonEditableAncestor && this.editor.editable.contains(nonEditableAncestor)) {
            const [anchorNode, anchorOffset] = rightPos(nonEditableAncestor);
            this.editor.shared.selection.setSelection({ anchorNode, anchorOffset });
        } else {
            this.editor.shared.selection.setCursorEnd(lastNode);
        }
        this.editor.shared.selection.selectAroundNonEditable();
    }

    get areAllActionsDisabled() {
        return false;
    }

    get isMultiUpload() {
        return true;
    }

    get placeholder() {
        if (this.props.placeholder) {
            return this.props.placeholder;
        }
        if (this.thread) {
            return this.thread.composerPlaceholder;
        }
        return "";
    }

    get wysiwygConfig() {
        return {
            content: this.props.composer.composerHtml,
            placeholder: this.placeholder,
            Plugins: this.ui.isSmall ? MAIL_SMALL_UI_PLUGINS : MAIL_PLUGINS,
            composerPluginDependencies: {
                onBeforePaste: (selection, ev) => this.onPaste(ev),
                onFocusin: this.onFocusin.bind(this),
                onFocusout: this.onFocusout.bind(this),
                onInput: this.onInput.bind(this),
                onKeydown: this.onKeydown.bind(this),
            },
            classList: ["o-mail-Composer-html"],
            onChange: () => this.onChangeWysiwygContent(),
            onEditorReady: () => {
                this.setEditorCursorEnd();
                this.editor.shared.history.addStep();
            },
        };
    }

    onClickCancelOrSaveEditText(ev) {
        const composer = toRaw(this.props.composer);
        if (composer.message && ev.target.dataset?.type === EDIT_CLICK_TYPE.CANCEL) {
            this.props.onDiscardCallback(ev);
        }
        if (composer.message && ev.target.dataset?.type === EDIT_CLICK_TYPE.SAVE) {
            this.editMessage(ev);
        }
    }

    get CANCEL_OR_SAVE_EDIT_TEXT() {
        const tags = {
            open_samp: markup`<samp>`,
            close_samp: markup`</samp>`,
            open_em: markup`<em>`,
            close_em: markup`</em>`,
            open_cancel: markup`<button class="btn btn-link fst-italic p-0 align-baseline" data-type="${EDIT_CLICK_TYPE.CANCEL}">`,
            close_cancel: markup`</button>`,
            open_save: markup`<button class="btn btn-link fst-italic p-0 align-baseline" data-type="${EDIT_CLICK_TYPE.SAVE}">`,
            close_save: markup`</button>`,
        };
        return this.env.inChatter
            ? _t(
                  "%(open_samp)sEscape%(close_samp)s %(open_em)sto %(open_cancel)scancel%(close_cancel)s%(close_em)s, %(open_samp)sCTRL-Enter%(close_samp)s %(open_em)sto %(open_save)ssave%(close_save)s%(close_em)s",
                  tags,
              )
            : _t(
                  "%(open_samp)sEscape%(close_samp)s %(open_em)sto %(open_cancel)scancel%(close_cancel)s%(close_em)s, %(open_samp)sEnter%(close_samp)s %(open_em)sto %(open_save)ssave%(close_save)s%(close_em)s",
                  tags,
              );
    }

    get SEND_TEXT() {
        if (this.props.composer.message) {
            return _t("Save editing");
        }
        return this.props.type === "note" ? _t("Log") : _t("Send");
    }

    get sendKeybinds() {
        return this.env.inChatter ? [_t("CTRL"), _t("Enter")] : [_t("Enter")];
    }

    get showComposerAvatar() {
        return !this.compact && this.props.sidebar;
    }

    get thread() {
        return this.props.composer.targetThread;
    }

    get allowUpload() {
        return this.props.allowUpload;
    }

    get message() {
        return this.props.composer.message ?? null;
    }

    get extraData() {
        return this.thread.rpcParams;
    }

    get isSendButtonDisabled() {
        const attachments = this.props.composer.attachments;
        return (
            !this.state.active ||
            (isHtmlEmpty(this.props.composer.composerHtml) &&
                attachments.length === 0) ||
            attachments.some(({ uploading }) => Boolean(uploading))
        );
    }

    get hasSuggestions() {
        return Boolean(this.suggestion?.state.items);
    }

    get navigableListProps() {
        const props = {
            anchorRef: this.inputContainerRef.el,
            position: this.env.inChatter ? "bottom-fit" : "top-fit",
            onSelect: (ev, option) => {
                this.suggestion.insert(option);
                markEventHandled(ev, "composer.selectSuggestion");
            },
            isLoading:
                !!this.suggestion.search.term && this.suggestion.state.isFetching,
            options: [],
        };
        if (!this.hasSuggestions) {
            return props;
        }
        return {
            ...props,
            ...mapSuggestionsToOptions(
                this.suggestion.state.items.type,
                this.suggestion.state.items.suggestions,
                { thread: this.thread },
            ),
        };
    }

    onDropFile(ev) {
        if (isDragSourceExternalFile(ev.dataTransfer)) {
            for (const file of ev.dataTransfer.files) {
                this.attachmentUploader.uploadFile(file);
            }
        }
    }

    onCloseFullComposerCallback(isDiscard) {
        if (this.props.onCloseFullComposerCallback) {
            this.props.onCloseFullComposerCallback(isDiscard);
        } else {
            this.thread?.fetchNewMessages();
        }
    }

    onInput(ev) {
        if (!this.props.composer.isDirty) {
            this.props.composer.isDirty = true;
        }
    }

    /**
     * This doesn't work on firefox https://bugzilla.mozilla.org/show_bug.cgi?id=1699743
     */
    onPaste(ev) {
        if (!this.allowUpload) {
            return;
        }
        if (!ev.clipboardData?.items) {
            return;
        }
        if (ev.clipboardData.files.length === 0) {
            return;
        }
        ev.preventDefault();
        for (const file of ev.clipboardData.files) {
            this.attachmentUploader.uploadFile(file);
        }
    }

    onKeydown(ev) {
        const composer = toRaw(this.props.composer);
        switch (ev.key) {
            case "ArrowUp":
                if (
                    !this.env.inChatter &&
                    composer.composerText === "" &&
                    composer.thread
                ) {
                    const messageToEdit = composer.thread.lastEditableMessageOfSelf;
                    if (messageToEdit) {
                        messageToEdit.enterEditMode(this.props.composer.thread);
                    }
                }
                break;
            case "Enter": {
                if (isEventHandled(ev, "NavigableList.select") || !this.state.active) {
                    ev.preventDefault();
                    return;
                }
                if (this.isMobileOS || ev.isComposing) {
                    return;
                }
                const shouldPost = this.env.inChatter ? ev.ctrlKey : !ev.shiftKey;
                if (!shouldPost) {
                    return;
                }
                ev.preventDefault(); // to prevent useless return
                if (composer.message) {
                    this.editMessage();
                } else {
                    this.sendMessage();
                }
                break;
            }
            case "Escape":
                if (isEventHandled(ev, "NavigableList.close")) {
                    return;
                }
                if (this.props.onDiscardCallback) {
                    this.props.onDiscardCallback();
                    markEventHandled(ev, "Composer.discard");
                }
                break;
        }
    }

    get fullComposerAdditionalContext() {
        // To be overridden by inheriting classes
        return {};
    }

    async onClickFullComposer() {
        await this.fullComposer.open();
    }

    /**
     * @param {string|ReturnType<markup>} defaultBody
     * @param {string|ReturnType<markup>} [signature=""]
     * @returns {ReturnType<markup>}
     */
    formatDefaultBodyForFullComposer(defaultBody, signature = "") {
        if (signature) {
            defaultBody = markup`${defaultBody}<br>${signature}`;
        }
        return markup`<div>${defaultBody}</div>`; // as to not wrap in <p> by html_sanitize
    }

    clear() {
        this.props.composer.clear();
        clearComposerDraft(this.props.composer);
    }

    notifySendFromMailbox() {
        this.store.notifySendFromMailbox(this.thread.displayName);
    }

    isEventTrusted(ev) {
        // Allow patching during tests
        return ev.isTrusted;
    }

    async processMessage(cb) {
        if (this.props.composer.attachments.some(({ uploading }) => uploading)) {
            this.env.services.notification.add(
                _t("Please wait while the file is uploading."),
                {
                    type: "warning",
                },
            );
        } else if (this.canProcessMessage) {
            if (!this.state.active) {
                return;
            }
            this.state.active = false;
            try {
                await cb(trimEmptyBlocksAround(this.props.composer.composerHtml));
                if (this.props.onPostCallback) {
                    this.props.onPostCallback();
                }
                // Only clear the composer on success; a failed post must keep
                // the user's draft.
                this.clear();
                this.ref.el?.focus();
            } finally {
                // Always re-enable: on a record thread cb() rethrows RPC
                // failures (unlike the fire-and-forget channel path), and
                // without this the composer stays disabled until remount,
                // silently swallowing every later send.
                this.state.active = true;
            }
        }
    }

    get canProcessMessage() {
        return (
            !isHtmlEmpty(this.props.composer.composerHtml) ||
            this.props.composer.attachments.length > 0 ||
            (this.message && this.message.attachment_ids.length > 0)
        );
    }

    async sendMessage() {
        const composer = toRaw(this.props.composer);
        this.composerActions.activePicker?.close?.();
        if (composer.message) {
            this.editMessage();
            return;
        }
        if (this.props.type !== "note") {
            const allRecipients = [
                ...composer.thread.suggestedRecipients,
                ...composer.thread.additionalRecipients,
            ];
            if (
                allRecipients.some(
                    (recipient) => !recipient.email || !isEmail(recipient.email),
                )
            ) {
                // Surface why nothing was sent instead of silently returning
                // (an unexplained no-op reads as a dead Send button).
                this.env.services.notification.add(
                    _t(
                        "Cannot send: a recipient has a missing or invalid email address.",
                    ),
                    { type: "danger" },
                );
                return;
            }
        }
        await this.processMessage(async (value) => {
            await this._sendMessage(value, this.postData, this.extraData);
        });
    }

    get postData() {
        const composer = toRaw(this.props.composer);
        return {
            attachments: composer.attachments || [],
            emailAddSignature: composer.emailAddSignature,
            isNote: this.props.type === "note",
            mentionedChannels: composer.mentionedChannels || [],
            mentionedPartners: composer.mentionedPartners || [],
            mentionedRoles: composer.mentionedRoles || [],
            cannedResponseIds: composer.cannedResponses.map((c) => c.id),
            parentId: this.props.composer.replyToMessage?.id,
        };
    }

    /**
     * @typedef postData
     * @property {import("models").Attachment[]} attachments
     * @property {boolean} isNote
     * @property {number} parentId
     * @property {integer[]} mentionedChannelIds
     * @property {integer[]} mentionedPartnerIds
     */

    /**
     * @param {ReturnType<markup>} value message body
     * @param {postData} postData Message meta data info
     * @param {extraData} extraData Message extra meta data info needed by other modules
     */
    async _sendMessage(value, postData, extraData) {
        const thread = toRaw(this.props.composer.thread);
        const postThread = toRaw(this.thread);
        const post = postThread.post.bind(postThread, value, postData, extraData);
        let message;
        if (postThread.hasOptimisticPost) {
            // feature of (optimistic) temp message
            post();
        } else {
            message = await post();
        }
        if (thread.isMailbox) {
            this.notifySendFromMailbox();
        }
        this.suggestion?.clearRawMentions();
        this.suggestion?.clearCannedResponses();
        this.props.composer.replyToMessage = undefined;
        this.props.composer.emailAddSignature = true;
        this.props.composer.thread.additionalRecipients = [];
        return message;
    }

    async editMessage() {
        const composer = toRaw(this.props.composer);
        if (!this.askDeleteFromEdit) {
            await this.processMessage(async (value) =>
                composer.message.edit(value, composer.attachments, {
                    mentionedChannels: composer.mentionedChannels,
                    mentionedPartners: composer.mentionedPartners,
                    mentionedRoles: composer.mentionedRoles,
                }),
            );
        } else {
            this.env.services.dialog.add(
                MessageConfirmDialog,
                {
                    message: composer.message,
                    onConfirm: () =>
                        this.message.remove({
                            removeFromThread: this.shouldHideFromMessageListOnDelete,
                        }),
                    prompt: _t(
                        "Are you sure you want to bid farewell to this message forever?",
                    ),
                },
                { context: this },
            );
        }
        this.suggestion?.clearRawMentions();
    }

    get askDeleteFromEdit() {
        const composer = toRaw(this.props.composer);
        return !composer.composerText && composer.message.attachment_ids.length === 0;
    }

    onClickInsertCannedResponse(ev) {
        markEventHandled(ev, "composer.clickInsertCannedResponse");
        const composer = toRaw(this.props.composer);
        let toInsert = "::";
        if (this.editor) {
            if (!isHtmlEmpty(this.props.composer.composerHtml)) {
                this.editor.shared.dom.insert(" ");
            }
        } else {
            const firstPart = composer.composerText.slice(0, composer.selection.start);
            if (firstPart.length !== 0 && firstPart.at(-1) !== " ") {
                toInsert = " ::";
            }
        }
        insertAtSelection(composer, toInsert, {
            editor: this.editor,
            moveCursor: (position) => this.selection.moveCursor(position),
        });
        if (!this.ui.isSmall || !this.env.inChatter) {
            composer.autofocus++;
        }
    }

    onChangeWysiwygContent() {
        this.updateFromEditor = true;
        // markup: editor content is trusted
        this.props.composer.composerHtml = markup(this.editor.getContent());
        if (!this.props.composer.isDirty) {
            this.props.composer.isDirty = true;
        }
        this.updateFromEditor = false;
    }

    onLoadWysiwyg(editor) {
        this.editor = editor;
    }

    addEmoji(str) {
        const composer = toRaw(this.props.composer);
        insertAtSelection(composer, str, {
            editor: this.editor,
            moveCursor: (position) => this.selection.moveCursor(position),
        });
        if (this.ui.isSmall && !this.env.inChatter) {
            return false;
        } else {
            composer.autofocus++;
        }
    }

    onFocusin(ev) {
        ev.stopPropagation();
        const composer = toRaw(this.props.composer);
        composer.isFocused = true;
        if (composer.thread) {
            markThreadAsReadIfAtBottom(composer.thread);
        }
    }

    onFocusout(ev) {
        if (
            [EDIT_CLICK_TYPE.CANCEL, EDIT_CLICK_TYPE.SAVE].includes(
                ev.relatedTarget?.dataset?.type,
            )
        ) {
            // Edit or Save most likely clicked: early return as to not re-render (which prevents click)
            return;
        }
        this.props.composer.isFocused = false;
    }

    saveContent() {
        const composer = toRaw(this.props.composer);
        if (composer.restoredFromFullComposer && !this.fullComposer.isOpen) {
            return;
        }
        if (this.fullComposer.isOpen) {
            this.fullComposer.saveContent();
        } else {
            saveComposerDraft(composer, {
                composerHtml: composer.composerHtml,
                emailAddSignature: true,
                replyToMessageId: composer.replyToMessage?.id,
                fromFullComposer: false,
            });
        }
    }

    restoreContent() {
        restoreComposerDraft(toRaw(this.props.composer));
    }

    get shouldHideFromMessageListOnDelete() {
        return false;
    }
}
