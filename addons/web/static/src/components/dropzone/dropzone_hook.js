// @ts-check
/** @odoo-module native */

import { onWillDestroy, useEffect, useExternalListener } from "@odoo/owl";
import { Dropzone } from "@web/components/dropzone/dropzone";
import { useService } from "@web/core/utils/hooks";

/**
 * @param {DragEvent} ev
 * @returns {boolean}
 */
function carriesFiles(ev) {
    return Boolean(ev.dataTransfer?.types.includes("Files"));
}

/**
 * Stops the browser from navigating to a file dropped outside a dropzone, and
 * reports the end of the drag session.
 *
 * Both `drop` and `dragend` end a session. `dragend` matters because it is the
 * only event a *cancelled* drag is guaranteed to produce: `dragenter` and
 * `dragleave` do not have to balance -- they fire per element crossed, and the
 * ones raised on a subtree that is torn down mid-drag are simply never
 * delivered. Without a `dragend` reset the counter can never return to zero and
 * the overlay stays on screen for the rest of the page's life.
 *
 * @param {() => void} onDragSessionEnd
 */
function useSuppressWindowFileDrop(onDragSessionEnd) {
    useExternalListener(window, "dragover", (ev) => {
        if (carriesFiles(ev)) {
            ev.preventDefault();
        }
    });
    useExternalListener(
        window,
        "drop",
        (ev) => {
            if (carriesFiles(ev)) {
                ev.preventDefault();
            }
            onDragSessionEnd();
        },
        { capture: true },
    );
    useExternalListener(window, "dragend", () => onDragSessionEnd(), {
        capture: true,
    });
}

/**
 * @param {any} targetRef
 * @param {import("@odoo/owl").ComponentConstructor} dropzoneComponent
 * @param {Object} dropzoneComponentProps
 * @param {function} isDropzoneEnabled
 */
export function useCustomDropzone(
    targetRef,
    dropzoneComponent,
    dropzoneComponentProps,
    isDropzoneEnabled = () => true,
) {
    const overlayService = useService("overlay");
    const uiService = useService("ui");

    let dragCount = 0;
    let hasTarget = false;
    /** @type {false|(() => void)} */
    let removeDropzone = false;

    useExternalListener(document, "dragenter", onDragEnter, { capture: true });
    useExternalListener(document, "dragleave", onDragLeave, { capture: true });
    useSuppressWindowFileDrop(() => {
        dragCount = 0;
        updateDropzone();
    });

    function updateDropzone() {
        const hasDropzone = !!removeDropzone;
        const isTargetInActiveElement = uiService.activeElement.contains(targetRef.el);
        const shouldDisplayDropzone =
            !!dragCount && hasTarget && isTargetInActiveElement && isDropzoneEnabled();

        if (shouldDisplayDropzone && !hasDropzone) {
            removeDropzone = overlayService.add(dropzoneComponent, {
                ref: targetRef,
                ...dropzoneComponentProps,
            });
        }
        if (!shouldDisplayDropzone && hasDropzone) {
            /** @type {any} */ (removeDropzone)();
            removeDropzone = false;
        }
    }

    function onDragEnter(/** @type {DragEvent} */ ev) {
        if (dragCount || carriesFiles(ev)) {
            dragCount++;
            updateDropzone();
        }
    }

    /**
     * @param {DragEvent} [ev]
     */
    function onDragLeave(ev) {
        if (!dragCount) {
            return;
        }
        dragCount = ev && !ev.relatedTarget ? 0 : dragCount - 1;
        updateDropzone();
    }

    useEffect(
        (el) => {
            hasTarget = !!el;
            updateDropzone();
        },
        () => [targetRef.el],
    );

    onWillDestroy(() => {
        if (removeDropzone) {
            removeDropzone();
            removeDropzone = false;
        }
    });
}

/**
 * `useCustomDropzone` with the stock overlay.
 *
 * @param {any} targetRef
 * @param {function} onDrop
 * @param {string} [extraClass]
 * @param {function} [isDropzoneEnabled]
 */
export function useDropzone(
    targetRef,
    onDrop,
    extraClass,
    isDropzoneEnabled = () => true,
) {
    useCustomDropzone(targetRef, Dropzone, { extraClass, onDrop }, isDropzoneEnabled);
}
