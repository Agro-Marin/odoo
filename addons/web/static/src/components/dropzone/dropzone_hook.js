// @ts-check
/** @odoo-module native */

/** @module @web/components/dropzone/dropzone_hook */

import { onWillDestroy, useEffect, useExternalListener } from "@odoo/owl";
import { Dropzone } from "@web/components/dropzone/dropzone";
import { useService } from "@web/core/utils/hooks";
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
    useExternalListener(window, "dragover", (ev) => {
        if (ev.dataTransfer && ev.dataTransfer.types.includes("Files")) {
            ev.preventDefault();
        }
    });
    useExternalListener(
        window,
        "drop",
        (ev) => {
            if (ev.dataTransfer && ev.dataTransfer.types.includes("Files")) {
                ev.preventDefault();
            }
            dragCount = 0;
            updateDropzone();
        },
        { capture: true },
    );

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
        if (dragCount || (ev.dataTransfer && ev.dataTransfer.types.includes("Files"))) {
            dragCount++;
            updateDropzone();
        }
    }

    function onDragLeave() {
        if (dragCount) {
            dragCount--;
            updateDropzone();
        }
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
    const dropzoneComponent = Dropzone;
    const dropzoneComponentProps = { extraClass, onDrop };
    useCustomDropzone(
        targetRef,
        dropzoneComponent,
        dropzoneComponentProps,
        isDropzoneEnabled,
    );
}
