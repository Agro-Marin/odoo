/** @odoo-module native */
import {
    Component,
    onMounted,
    onWillUnmount,
    onWillUpdateProps,
    useComponent,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { deepEqual } from "@web/core/utils/collections/objects";
import { useService } from "@web/core/utils/hooks";
import { hidePDFJSButtons } from "@web/core/utils/pdfjs";
class AbstractAttachmentView extends Component {
    static template = "mail.AttachmentView";
    static components = {};
    static props = ["threadId", "threadModel"];

    setup() {
        super.setup();
        this.store = useService("mail.store");
        this.uiService = useService("ui");
        this.iframeViewerPdfRef = useRef("iframeViewerPdf");
        this.state = useState({
            /** @type {import("models").Thread|undefined} */
            thread: undefined,
        });
        useEffect(
            /** @param {HTMLIFrameElement|null} el */
            (el) => {
                if (el) {
                    hidePDFJSButtons(this.iframeViewerPdfRef.el);
                }
            },
            () => [this.iframeViewerPdfRef.el],
        );
        this.updateFromProps(this.props);
        onWillUpdateProps(
            /** @param {{threadId: number, threadModel: string}} props */ (props) =>
                this.updateFromProps(props),
        );
    }

    onClickNext() {
        const index = this.state.thread.attachmentsInWebClientView.findIndex(
            (attachment) => attachment.eq(this.state.thread.message_main_attachment_id),
        );
        this.state.thread.setMainAttachmentFromIndex(
            index >= this.state.thread.attachmentsInWebClientView.length - 1
                ? 0
                : index + 1,
        );
    }

    onClickPrevious() {
        const index = this.state.thread.attachmentsInWebClientView.findIndex(
            (attachment) => attachment.eq(this.state.thread.message_main_attachment_id),
        );
        this.state.thread.setMainAttachmentFromIndex(
            index <= 0
                ? this.state.thread.attachmentsInWebClientView.length - 1
                : index - 1,
        );
    }

    /** @param {{threadId: number, threadModel: string}} props */
    updateFromProps(props) {
        this.state.thread = this.store.Thread.insert({
            id: props.threadId,
            model: props.threadModel,
        });
    }

    get displayName() {
        return this.state.thread.message_main_attachment_id.name;
    }

    onClickPopout() {}
}

export class PopoutAttachmentView extends AbstractAttachmentView {
    static template = "mail.PopoutAttachmentView";
}

/** @returns {DOMTokenList|null} */
function attachmentViewParentElementClassList() {
    const attachmentViewEl = document.querySelector(".o-mail-Attachment");
    return attachmentViewEl?.parentElement?.classList ?? null;
}
/** @param {boolean} hidden */
function setAttachmentViewHidden(hidden) {
    attachmentViewParentElementClassList()?.toggle("d-none", hidden);
}
/**
 * @param {{threadId: number, threadModel: string}} props
 * @returns {{threadId: number, threadModel: string}}
 */
function extractPopoutProps(props) {
    return {
        threadId: props.threadId,
        threadModel: props.threadModel,
    };
}
export function usePopoutAttachment() {
    const component = useComponent();
    const uiService = useService("ui");
    const mailPopoutService = useService("mail.popout");

    function popout() {
        mailPopoutService.addHooks(
            () => {
                setAttachmentViewHidden(true);
                uiService.bus.trigger("resize");
            },
            () => {
                setAttachmentViewHidden(false);
                uiService.bus.trigger("resize");
            },
        );
        mailPopoutService.popout(
            PopoutAttachmentView,
            extractPopoutProps(component.props),
        );
    }

    /** @param {{threadId: number, threadModel: string}} [newProps=component.props] */
    function updatePopout(newProps = component.props) {
        if (mailPopoutService.externalWindow) {
            setAttachmentViewHidden(true);
            mailPopoutService.popout(
                PopoutAttachmentView,
                extractPopoutProps(newProps),
            );
        }
    }

    function resetPopout() {
        mailPopoutService.reset();
    }

    onMounted(updatePopout);
    onWillUpdateProps(
        /** @param {{threadId: number, threadModel: string}} props */ (props) => {
            const oldProps = extractPopoutProps(component.props);
            const newProps = extractPopoutProps(props);
            if (!deepEqual(oldProps, newProps)) {
                updatePopout(newProps);
            }
        },
    );
    onWillUnmount(resetPopout);
    return {
        popout,
        updatePopout,
        resetPopout,
    };
}

/**
 * @typedef {Object} Props
 * @property {number} threadId
 * @property {string} threadModel
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class AttachmentView extends AbstractAttachmentView {
    setup() {
        super.setup();
        this.attachmentPopout = usePopoutAttachment();
    }

    onClickPopout() {
        this.attachmentPopout.popout();
    }
}
