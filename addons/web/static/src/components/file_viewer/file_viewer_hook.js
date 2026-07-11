// @ts-check
/** @odoo-module native */

/** @module @web/components/file_viewer/file_viewer_hook - Factory and hook for opening/closing a file viewer as a main component */

import { onWillDestroy } from "@odoo/owl";
import { registry } from "@web/core/registry";

import { FileViewer } from "./file_viewer.js";
let id = 1;

export function createFileViewer() {
    const fileViewerId = `web.file_viewer${id++}`;
    /**
     * @param {{ name: string, isViewable: boolean, [key: string]: any }} file
     * @param {{ name: string, isViewable: boolean, [key: string]: any }[]} files
     */
    function open(file, files = [file]) {
        close();
        if (!file.isViewable) {
            return;
        }
        if (files.length) {
            const viewableFiles = files.filter((file) => file.isViewable);
            // `file` may not be identical to any entry of `files` (e.g. a
            // copy): never mount the viewer with startIndex -1.
            const index = Math.max(0, viewableFiles.indexOf(file));
            registry.category("main_components").add(
                fileViewerId,
                /** @type {any} */ ({
                    Component: FileViewer,
                    props: { files: viewableFiles, startIndex: index, close },
                }),
            );
        }
    }

    function close() {
        const mainComponents = registry.category("main_components");
        if (mainComponents.contains(fileViewerId)) {
            mainComponents.remove(fileViewerId);
        }
    }
    return { open, close };
}

export function useFileViewer() {
    const { open, close } = createFileViewer();
    onWillDestroy(close);
    return { open, close };
}
