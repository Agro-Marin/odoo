/** @odoo-module native */
import { useEnv, useState, useSubEnv } from "@odoo/owl";
import { useListener } from "@web/core/utils/owl_bridge";

function isSmall() {
    return window.innerWidth < 960;
}

/** @param {{ isSmall: boolean, size: number }} ui */
function provideDocUI(ui) {
    useSubEnv({ ui });
}

/** @returns {{ isSmall: boolean, size: number } | undefined} */
function useParentDocUI() {
    return useEnv().ui;
}

export function useDocUI() {
    const parentUI = useParentDocUI();
    if (parentUI) {
        return useState(parentUI);
    }
    const ui = useState({
        isSmall: isSmall(),
        size: window.innerWidth,
    });

    provideDocUI(ui);
    useListener(window, "resize", () => {
        ui.size = window.innerWidth;
        ui.isSmall = isSmall();
    });

    return ui;
}
