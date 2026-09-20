import { expect, test } from "@odoo/hoot";
import { insertKioskStyle } from "@pos_self_order/app/kiosk_style";

test("kiosk styles keep light and dark brand contrast", () => {
    for (const [color, rgb, text] of [
        ["#fff", "255, 255, 255", "#0d0d0d"],
        [" #fff ", "255, 255, 255", "#0d0d0d"],
        ["\t#ABCDEF\n", "171, 205, 239", "#090a0c"],
        ["#000", "0, 0, 0", "#f2f2f2"],
        ["#875A7B", "113, 75, 103", "#f8f6f7"],
    ]) {
        insertKioskStyle(color);
        const style = document.head.lastElementChild;
        try {
            expect(
                style.sheet.cssRules[0].style.getPropertyValue("--primary-rgb"),
            ).toBe(rgb);
            expect(style.sheet.cssRules[1].style.getPropertyValue("--btn-color")).toBe(
                text,
            );
        } finally {
            style.remove();
        }
    }
});
