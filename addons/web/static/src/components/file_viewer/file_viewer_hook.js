// @ts-check
/** @odoo-module native */

import { onWillDestroy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { uniqueId } from "@web/core/utils/functions";

import { FileViewer } from "./file_viewer.js";

export function createFileViewer() {
    const fileViewerId = uniqueId("web.file_viewer");
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
