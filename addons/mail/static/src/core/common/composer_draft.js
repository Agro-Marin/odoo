/** @odoo-module native */
import {
    Component,
    onMounted,
    useComponent,
    useEffect,
    useExternalListener,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { isHtmlEmpty, isMarkup } from "@web/core/utils/dom/html";
import { useDebounced } from "@web/core/utils/timing";
import { usePopover } from "@web/ui/popover";

/**
 * @typedef {Object} ComposerDraft
 * @property {string|ReturnType<markup>|["markup", string]} composerHtml
 * @property {boolean} emailAddSignature
 * @property {number} [replyToMessageId]
 * @property {boolean} [fromFullComposer=false]
 */
/**
 * @param {import("models").Composer} composer
 * @param {ComposerDraft} draft
 */
export function saveComposerDraft(
    composer,
    { composerHtml, emailAddSignature, replyToMessageId, fromFullComposer = false },
) {
    if (isHtmlEmpty(composerHtml)) {
        browser.localStorage.removeItem(composer.localId);
    } else {
        browser.localStorage.setItem(
            composer.localId,
            JSON.stringify({
                emailAddSignature,
                replyToMessageId,
                composerHtml: isMarkup(composerHtml)
                    ? ["markup", composerHtml]
                    : composerHtml,
                fromFullComposer,
            }),
        );
    }
}

/** @param {import("models").Composer} composer */
export function restoreComposerDraft(composer) {
    let config;
    try {
        config = JSON.parse(browser.localStorage.getItem(composer.localId));
    } catch {
        browser.localStorage.removeItem(composer.localId);
    }
    if (!config) {
        return;
    }
    if (!isHtmlEmpty(config.composerHtml)) {
        if (composer.thread && !composer.thread.isChannelKind) {
            composer.restoredFromFullComposer = config.fromFullComposer;
        }
        composer.emailAddSignature = config.emailAddSignature;
        composer.composerHtml = config.composerHtml;
    }
    if (Number.isInteger(config.replyToMessageId)) {
        composer.replyToMessage = composer.store["mail.message"].insert(
            config.replyToMessageId,
        );
    }
}

/** @param {import("models").Composer} composer */
export function clearComposerDraft(composer) {
    browser.localStorage.removeItem(composer.localId);
}

export class FullComposerRecoveryPopover extends Component {
    static props = ["composer", "onClickFullRecover", "onClickTextRecover", "close?"];
    static template = "mail.FullComposerRecoveryPopover";

    onClickFullRecover() {
        this.props.onClickFullRecover();
        this.props.close();
    }

    onClickTextRecover() {
        this.props.onClickTextRecover();
        this.props.close();
    }
}

export function useComposerDraft() {
    const comp = useComponent();
    const saveContentDebounced = useDebounced(() => comp.saveContent(), 5000, {
        execBeforeUnmount: true,
    });
    useExternalListener(window, "beforeunload", () => comp.saveContent());
    useEffect(
        () => {
            saveContentDebounced();
        },
        () => [comp.props.composer.composerText, comp.ref.el],
    );
    onMounted(() => {
        if (!comp.props.composer.composerText) {
            comp.restoreContent();
        }
    });
    const recoveryPopover = usePopover(FullComposerRecoveryPopover, {
        closeOnClickAway: false,
        closeOnEscape: false,
        position: "top-end",
        popoverClass: "dropdown-menu bg-view overflow-visible o-rounded-bubble mx-1",
    });
    useEffect(
        /**
         * @param {boolean} isFullComposerOpen
         * @param {boolean} restoredFromFullComposer
         * @param {HTMLElement|null} fullComposerButtonEl
         */
        (isFullComposerOpen, restoredFromFullComposer, fullComposerButtonEl) => {
            if (
                isFullComposerOpen ||
                !restoredFromFullComposer ||
                !fullComposerButtonEl
            ) {
                recoveryPopover.close();
                return;
            }
            if (recoveryPopover.isOpen) {
                return;
            }
            recoveryPopover.open(fullComposerButtonEl, {
                composer: comp.props.composer,
                onClickFullRecover: () => {
                    comp.onClickFullComposer();
                    comp.props.composer.restoredFromFullComposer = false;
                },
                onClickTextRecover: () => {
                    comp.props.composer.restoredFromFullComposer = false;
                },
            });
        },
        () => [
            comp.fullComposer.isOpen,
            comp.props.composer.restoredFromFullComposer,
            comp.root.el?.querySelector("button[name='open-full-composer']"),
        ],
    );
    return { recoveryPopover, saveContentDebounced };
}
