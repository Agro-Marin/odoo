// @ts-check
/** @odoo-module native */
/* eslint-disable no-console -- QA automation bot; progress/results output to console is its purpose */

/** @module @web/webclient/clickbot/clickbot */

import { App, reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { AppEvent, RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { getPopoverForTarget } from "@web/ui/popover/popover";

export const SUCCESS_SIGNAL = "clickbot test succeeded";

const MOUSE_EVENTS = ["mouseover", "mouseenter", "mousedown", "mouseup", "click"];
const BLACKLISTED_MENUS = [
    "base.menu_theme_store",
    "base.menu_third_party",
    "event.menu_event_registration_desk",
    "hr_attendance.menu_action_open_form",
    "hr_attendance.menu_hr_attendance_onboarding",
    "mrp_workorder.menu_mrp_workorder_root",
    "pos_enterprise.menu_point_kitchen_display_root",
];
const STUDIO_SYSTRAY_ICON_SELECTOR = ".o_web_studio_navbar_item:not(.o_disabled) i";

let isEnterprise;
let state;
let calledRPC;
let errorRPC;
let actionCount;
let env;
let apps;

function setup(light, currentState) {
    env = /** @type {any} */ (odoo).__WOWL_DEBUG__.root.env;
    const stopButton = document.createElement("button");
    stopButton.setAttribute("id", "stop-clickbot");
    stopButton.classList.add("btn", "btn-danger");
    stopButton.textContent = "Stop ClickAll!";
    stopButton.onclick = function () {
        browser.localStorage.removeItem("running.clickbot");
        browser.location.reload();
    };
    document.body.appendChild(stopButton);

    env.bus.addEventListener(AppEvent.ACTION_MANAGER_UI_UPDATED, uiUpdate);
    rpcBus.addEventListener(RpcEvent.REQUEST, /** @type {any} */ (onRPCRequest));
    rpcBus.addEventListener(RpcEvent.RESPONSE, /** @type {any} */ (onRPCResponse));
    isEnterprise = odoo.info && odoo.info.isEnterprise;

    state = reactive(
        currentState || {
            light,
            studioCount: 0,
            testedApps: [],
            testedMenus: [],
            testedFilters: 0,
            testedModals: 0,
            appIndex: 0,
            menuIndex: 0,
            subMenuIndex: 0,
        },
        () => browser.localStorage.setItem("running.clickbot", JSON.stringify(state)),
    );
    browser.localStorage.setItem("running.clickbot", JSON.stringify(state));

    actionCount = 0;
    calledRPC = {};
    apps = null;
    errorRPC = undefined;
}

function onRPCRequest({ detail }) {
    calledRPC[detail.data.id] = detail.url;
}

function onRPCResponse({ detail }) {
    if (!detail?.data) {
        return;
    }
    delete calledRPC[detail.data.id];
    if (detail.error) {
        errorRPC = { ...detail };
    }
}

function uiUpdate() {
    actionCount++;
}

function cleanup() {
    browser.localStorage.removeItem("running.clickbot");
    env.bus.removeEventListener(AppEvent.ACTION_MANAGER_UI_UPDATED, uiUpdate);
    rpcBus.removeEventListener(RpcEvent.REQUEST, /** @type {any} */ (onRPCRequest));
    rpcBus.removeEventListener(RpcEvent.RESPONSE, /** @type {any} */ (onRPCResponse));
    document.getElementById("stop-clickbot")?.remove();
}

/**
 * @returns {Promise}
 */
async function waitForNextAnimationFrame() {
    await new Promise(/** @type {any} */ (browser.setTimeout));
    await new Promise((r) => browser.requestAnimationFrame(r));
}

/**
 * @param {EventTarget} target
 * @param {string} elDescription
 * @returns {Promise}
 */
async function triggerClick(target, elDescription) {
    if (target) {
        if (elDescription) {
            browser.console.log(`Clicking on: ${elDescription}`);
        }
    } else {
        throw new Error(`No element "${elDescription}" found.`);
    }
    MOUSE_EVENTS.forEach((type) => {
        const event = new MouseEvent(type, {
            bubbles: true,
            cancelable: true,
            view: window,
        });
        target.dispatchEvent(event);
    });
    await waitForNextAnimationFrame();
}

/**
 * @param {function} stopCondition
 * @returns {Promise}
 */
async function waitForCondition(stopCondition) {
    const interval = 25;
    const initialTime = 30000;
    let timeLimit = initialTime;

    function hasPendingRPC() {
        return Object.keys(calledRPC).length > 0;
    }
    function hasScheduledTask() {
        let size = 0;
        for (const app of /** @type {any} */ (App).apps) {
            size += app.scheduler.tasks.size;
        }
        return size > 0;
    }
    function errorDialog() {
        if (document.querySelector(".o_error_dialog")) {
            if (errorRPC) {
                browser.console.error(
                    "A RPC in error was detected, maybe it's related to the error dialog : " +
                        JSON.stringify(errorRPC),
                );
            }
            throw new Error(
                "Error dialog detected" +
                    document.querySelector(".o_error_dialog").innerHTML,
            );
        }
        return false;
    }

    while (errorDialog() || !stopCondition() || hasPendingRPC() || hasScheduledTask()) {
        if (timeLimit <= 0) {
            let msg = `Timeout, the clicked element took more than ${
                initialTime / 1000
            } seconds to load\n`;
            msg += `Waiting for:\n`;
            if (Object.keys(calledRPC).length > 0) {
                msg += ` * ${Object.values(calledRPC).join(", ")} RPC\n`;
            }
            let scheduleTasks = "";
            for (const app of /** @type {any} */ (App).apps) {
                for (const task of app.scheduler.tasks) {
                    scheduleTasks += `${task.node.name},`;
                }
            }
            if (scheduleTasks.length) {
                msg += ` * ${scheduleTasks} scheduled tasks\n`;
            }
            if (!stopCondition()) {
                msg += ` * stopCondition: ${stopCondition.toString()}`;
            }
            throw new Error(msg);
        }
        await new Promise((resolve) => browser.setTimeout(resolve, interval));
        timeLimit -= interval;
    }
}

async function ensureHomeMenu() {
    const homeMenu = document.querySelector("div.o_home_menu");
    if (!homeMenu) {
        let menuToggle = document.querySelector("nav.o_main_navbar > a.o_menu_toggle");
        if (!menuToggle) {
            menuToggle = document.querySelector(".o_stock_barcode_home_menu");
        }
        await triggerClick(menuToggle, "home menu toggle button");
        await waitForCondition(() => document.querySelector("div.o_home_menu"));
    }
}

async function ensureAppsMenu() {
    const apps = document.querySelectorAll(".o-dropdown--menu .o_app");
    if (!apps || !apps.length) {
        const toggler = document.querySelector(".o_navbar_apps_menu .dropdown-toggle");
        await triggerClick(toggler, "apps menu toggle button");
        await waitForCondition(() =>
            document.querySelector(".o-dropdown--menu .o_app"),
        );
    }
}

/**
 * @returns {Promise<Element | undefined>}
 */
async function getNextMenu() {
    const menuToggles = document.querySelectorAll(
        ".o_menu_sections > .dropdown-toggle, .o_menu_sections > .dropdown-item",
    );
    if (state.menuIndex >= menuToggles.length) {
        state.menuIndex = 0;
        return;
    }
    let menuToggle = menuToggles[state.menuIndex];
    if (menuToggle.classList.contains("dropdown-toggle")) {
        let dropdownMenu = getPopoverForTarget(/** @type {HTMLElement} */ (menuToggle));
        if (!dropdownMenu) {
            await triggerClick(menuToggle, "menu toggler");
            dropdownMenu = getPopoverForTarget(/** @type {HTMLElement} */ (menuToggle));
        }
        if (!dropdownMenu) {
            state.menuIndex = 0;
            return;
        }
        const items = dropdownMenu.querySelectorAll(".dropdown-item");
        if (state.subMenuIndex >= items.length) {
            state.menuIndex++;
            state.subMenuIndex = 0;
            return;
        }
        menuToggle = items[state.subMenuIndex];
        if (state.subMenuIndex === items.length - 1) {
            state.menuIndex++;
            state.subMenuIndex = 0;
        } else {
            state.subMenuIndex++;
        }
    } else {
        state.menuIndex++;
    }
    return menuToggle;
}

/**
 * @returns {Promise<string | undefined>}
 */
async function getNextApp() {
    if (!apps || !apps.length) {
        if (isEnterprise) {
            await ensureHomeMenu();
            apps = document.querySelectorAll(".o_apps .o_app");
        } else {
            await ensureAppsMenu();
            apps = document.querySelectorAll(".o-dropdown--menu .o_app");
        }
    }
    const appName = /** @type {HTMLElement} */ (apps[state.appIndex])?.dataset
        ?.menuXmlid;
    state.appIndex++;
    return appName;
}

async function testStudio() {
    const studioIcon = document.querySelector(STUDIO_SYSTRAY_ICON_SELECTOR);
    if (!studioIcon) {
        return;
    }
    await triggerClick(studioIcon, "entering studio");
    await waitForCondition(() => document.querySelector(".o_in_studio"));
    await triggerClick(document.querySelector(".o_web_studio_leave"), "leaving studio");
    await waitForCondition(() =>
        document.querySelector(".o_main_navbar:not(.o_studio_navbar) .o_menu_toggle"),
    );
    state.studioCount++;
}

async function testFilters() {
    if (state.light === true) {
        return;
    }
    const searchBarMenu = document.querySelector(
        ".o_control_panel .dropdown-toggle.o_searchview_dropdown_toggler",
    );
    if (!searchBarMenu) {
        return;
    }
    await triggerClick(searchBarMenu, "search bar menu dropdown");
    const filterMenuButton = document.querySelector(
        ".o_dropdown_container.o_filter_menu",
    );
    if (!filterMenuButton) {
        return;
    }

    const simpleFilterSel =
        ".o_filter_menu > .dropdown-item.o_menu_item:not(.o_add_custom_filter)";
    const dateFilterSel = ".o_filter_menu > .o_accordion";
    const filterMenuItems = document.querySelectorAll(
        `${simpleFilterSel},${dateFilterSel}`,
    );
    browser.console.log(`Testing ${filterMenuItems.length} filters`);
    state.testedFilters += filterMenuItems.length;
    for (const filter of filterMenuItems) {
        if (filter.classList.contains("o_accordion")) {
            await triggerClick(
                filter.querySelector(".o_accordion_toggle"),
                `filter "${/** @type {HTMLElement} */ (filter).innerText.trim()}"`,
            );

            const firstOption = filter.querySelector(
                ".o_accordion > .o_accordion_values > .dropdown-item",
            );
            if (firstOption) {
                await triggerClick(
                    firstOption,
                    `filter option "${/** @type {HTMLElement} */ (firstOption).innerText.trim()}"`,
                );
                await waitForCondition(() => true);
            }
        } else {
            await triggerClick(
                filter,
                `filter "${/** @type {HTMLElement} */ (filter).innerText.trim()}"`,
            );
            await waitForCondition(() => true);
        }
    }
}

/**
 * @returns {Promise}
 */
async function testViews() {
    if (state.light === true) {
        return;
    }
    const switchButtons = document.querySelectorAll(
        "nav.o_cp_switch_buttons > button.o_switch_view:not(.active):not(.o_map)",
    );
    for (const switchButton of switchButtons) {
        const viewTypeClass = [...switchButton.classList].find(
            (cls) => cls !== "o_switch_view" && cls.startsWith("o_"),
        );
        if (!viewTypeClass) {
            browser.console.warn(
                "Skipping a view switcher with no o_<viewtype> class:",
                switchButton.className,
            );
            continue;
        }
        const viewType = viewTypeClass.slice(2);
        browser.console.log(`Testing view switch: ${viewType}`);
        await new Promise((resolve) => browser.setTimeout(resolve, 250));
        const target = document.querySelector(
            `nav.o_cp_switch_buttons > button.o_switch_view.o_${viewType}`,
        );
        if (!target) {
            browser.console.warn(`View switcher for ${viewType} disappeared`);
            continue;
        }
        await triggerClick(target, `${viewType} view switcher`);
        await waitForCondition(
            () =>
                document.querySelector(`.o_switch_view.o_${viewType}.active`) !== null,
        );
        await testStudio();
        await testFilters();
    }
}

/**
 * @param {Element} element
 * @returns {Promise}
 */
async function testMenuItem(element) {
    const el = /** @type {HTMLElement} */ (element);
    const menu = el.dataset.menuXmlid;
    const menuDescription = `${el.innerText.trim()} ${menu}`;
    if (BLACKLISTED_MENUS.includes(menu)) {
        browser.console.log(`Skipping blacklisted menu ${menuDescription}`);
        return Promise.resolve();
    }
    browser.console.log(`Testing menu ${menuDescription}`);
    if (!state.testedMenus.includes(menu)) {
        state.testedMenus.push(menu);
    }
    const startActionCount = actionCount;
    await triggerClick(element, `menu item "${el.innerText.trim()}"`);
    try {
        let isModal = false;
        await waitForCondition(() => {
            if (!isModal && document.querySelector(".o_dialog:not(.o_error_dialog)")) {
                isModal = true;
                browser.console.log(`Modal detected: ${menuDescription}`);
                state.testedModals++;
                return true;
            }
            return isModal || startActionCount !== actionCount;
        });
        if (isModal) {
            await triggerClick(
                document.querySelector(".o_dialog header > .btn-close"),
                "modal close button",
            );
        } else {
            await testStudio();
            await testFilters();
            await testViews();
        }
    } catch (err) {
        browser.console.error(`Error while testing ${menuDescription}`);
        throw err;
    }
}

/**
 * @returns {Promise}
 */
async function testApp() {
    let element;

    if (!state.testedApps.includes(state.app)) {
        if (isEnterprise) {
            await ensureHomeMenu();
            element = document.querySelector(
                `a.o_app.o_menuitem[data-menu-xmlid="${state.app}"]`,
            );
        } else {
            await ensureAppsMenu();
            element = document.querySelector(
                `.o-dropdown--menu .dropdown-item[data-menu-xmlid="${state.app}"]`,
            );
        }
        if (!element) {
            throw new Error(`No app found for xmlid ${state.app}`);
        }
        browser.console.log(`Testing app menu: ${state.app}`);
        state.testedApps.push(state.app);
        await testMenuItem(element);
    } else {
        browser.console.log(`already tested app ${state.app}`);
    }

    if (state.light === true) {
        return;
    }
    let menu = await getNextMenu();
    while (menu) {
        await testMenuItem(menu);
        menu = await getNextMenu();
    }
}

async function _clickEverywhere(xmlId, light, currentState) {
    setup(light, currentState);
    console.log("Starting ClickEverywhere test");
    console.log(`Odoo flavor: ${isEnterprise ? "Enterprise" : "Community"}`);
    const startTime = performance.now();
    try {
        if (xmlId) {
            state.xmlId = xmlId;
            state.app = xmlId;
            await testApp();
        } else {
            if (state.app) {
                await testApp();
            }
            while ((state.app = await getNextApp())) {
                state.menuIndex = 0;
                state.subMenuIndex = 0;
                await testApp();
            }
        }

        console.log(`Test took ${(performance.now() - startTime) / 1000} seconds`);
        browser.console.log(`Successfully tested ${state.testedApps.length} apps`);
        browser.console.log(
            `Successfully tested ${state.testedMenus.length - state.testedApps.length} menus`,
        );
        browser.console.log(`Successfully tested ${state.testedModals} modals`);
        browser.console.log(`Successfully tested ${state.testedFilters} filters`);
        if (state.studioCount > 0) {
            browser.console.log(
                `Successfully tested ${state.studioCount} views in Studio`,
            );
        }
        browser.console.log(SUCCESS_SIGNAL);
    } catch (err) {
        console.log(`Test took ${(performance.now() - startTime) / 1000} seconds`);
        browser.console.error(err || "test failed");
    } finally {
        cleanup();
    }
}

function clickEverywhere(xmlId, light = false, currentState) {
    browser.setTimeout(_clickEverywhere, 1000, xmlId, light, currentState);
}

/** @type {any} */ (window).clickEverywhere = clickEverywhere;
