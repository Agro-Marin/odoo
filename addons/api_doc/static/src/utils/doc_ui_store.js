/** @odoo-module native */
import { useEnv, useExternalListener, useState, useSubEnv } from "@odoo/owl";

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
    useExternalListener(window, "resize", () => {
        ui.size = window.innerWidth;
        ui.isSmall = isSmall();
    });

    return ui;
}
