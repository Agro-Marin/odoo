/** @odoo-module native */
import {
    colorToRgb,
    getColorBrightness,
    mixHexColors,
} from "@web/core/utils/format/colors";
export function insertKioskStyle(primaryBgColor) {
    const style = document.createElement("style");
    style.textContent = generateKioskCSS(primaryBgColor);
    document.head.appendChild(style);
}

function generateKioskCSS(companyPrimaryColor) {
    let bgPrimary = companyPrimaryColor;
    if (!bgPrimary || bgPrimary === "#875A7B") {
        bgPrimary = "#714B67";
    }
    const luminance = getColorBrightness(bgPrimary);
    const isLightBackground = luminance > 0.55;
    const shadedPrimary = mixHexColors("#000000", bgPrimary, 0.6);

    const textBgPrimary = isLightBackground
        ? mixHexColors("#000000", bgPrimary, 0.95)
        : mixHexColors("#FFFFFF", bgPrimary, 0.95);
    const primaryTextBorder = isLightBackground ? shadedPrimary : bgPrimary;

    const buttonActiveColor = mixHexColors("#000000", bgPrimary, 0.2);

    return `
        :root {
            --primary-rgb: ${colorToRgb(bgPrimary)};
            --primary: ${bgPrimary};
        }

        .btn-primary {
            --btn-color: ${textBgPrimary};
            --btn-bg: ${bgPrimary};
            --btn-border-color: ${bgPrimary};
            --btn-hover-color: ${textBgPrimary};
            --btn-hover-bg: ${bgPrimary};
            --btn-hover-border-color: ${bgPrimary};
            --btn-focus-shadow-rgb: ${colorToRgb(mixHexColors(textBgPrimary, bgPrimary, 0.15))};
            --btn-active-color: ${textBgPrimary};
            --btn-active-bg: ${buttonActiveColor};
            --btn-active-border-color: ${buttonActiveColor};
            --btn-active-shadow: 0;
            --btn-disabled-color: ${textBgPrimary};
            --btn-disabled-bg: ${bgPrimary};
            --btn-disabled-border-color: ${bgPrimary};
        }

        .text-primary {
            --color: rgba(${colorToRgb(primaryTextBorder)}, var(--text-opacity, 1));
        }

        .border-primary {
            border-color: ${primaryTextBorder} !important;
        }

        .text-bg-primary :is(h1, h2, h3, h4, h5, h6) {
            color: ${textBgPrimary};
        }
      
        .text-bg-primary .btn-link, .badge.text-bg-primary, .btn.text-bg-primary {
            color: ${textBgPrimary} !important;
        }

        .text-bg-primary .btn-link:hover {
            color: ${mixHexColors(textBgPrimary, bgPrimary, 0.85)} !important;
        }

        .o_self_background {
            background-color: ${mixHexColors("#ffffff", bgPrimary, 0.85)};
        }
    `;
}
