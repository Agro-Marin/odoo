import { escapeRegExp } from "@web/core/utils/format/strings";

export const buttonTriger = (buttonValue) =>
    `div.numpad button:contains(/^${escapeRegExp(buttonValue)}$/)`;

export const click = (buttonValue) => ({
    content: `click numpad button: ${buttonValue}`,
    trigger: buttonTriger(buttonValue),
    run: "click",
});
export const enterValue = (keys) => keys.split("").map((key) => click(key));
export const isActive = (buttonValue) => ({
    content: `check if --${buttonValue}-- mode is activated`,
    trigger: `${buttonTriger(buttonValue)}.active`,
});

export const isVisible = () => ({
    content: "check if numpad is visible",
    trigger: "div.numpad:visible",
});
