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
import { usePopover } from "@web/ui/popover/popover_hook";

/**
 * Draft persistence for composers.
 *
 * Drafts are stored in the browser's localStorage, keyed by the composer
 * record's `localId`. The key (and the stored payload shape) are kept
 * identical to what the Composer component historically used, so drafts
 * saved before this module existed keep being restored.
 */

/**
 * @typedef {Object} ComposerDraft
 * @property {string|ReturnType<markup>|["markup", string]} composerHtml
 * @property {boolean} emailAddSignature
 * @property {number} [replyToMessageId]
 * @property {boolean} [fromFullComposer=false] whether the draft content was
 *   saved from the full composer dialog (formatting can only be recovered
 *   there)
 */

/**
 * Persists a draft for `composer`, or removes the stored draft when
 * `composerHtml` is empty.
 *
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

/**
 * Restores the draft stored for `composer` (if any) onto the record. A
 * corrupted stored draft is dropped.
 *
 * @param {import("models").Composer} composer
 */
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
        if (composer.thread && composer.thread?.model !== "discuss.channel") {
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

/**
 * Removes the draft stored for `composer` (if any).
 *
 * @param {import("models").Composer} composer
 */
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

/**
 * Wires draft persistence on a Composer component:
 *
 * - debounced save on content change and save on `beforeunload`;
 * - restore of the stored draft on mount (when the composer is empty);
 * - the "recover from full composer?" popover shown when the restored draft
 *   was saved from the full composer dialog.
 *
 * Saving/restoring goes through the component's `saveContent()` /
 * `restoreContent()` so downstream patches of those methods keep applying.
 */
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
