/** @odoo-module alias=@odoo/hoot-mock default=false */

import * as _hootDom from "@odoo/hoot-dom";

import * as _animation from "./mock/animation.js";
import * as _date from "./mock/date.js";
import * as _math from "./mock/math.js";
import * as _navigator from "./mock/navigator.js";
import * as _network from "./mock/network.js";
import * as _notification from "./mock/notification.js";
import * as _window from "./mock/window.js";

/** @deprecated */
export const advanceFrame = _hootDom.advanceFrame;
/** @deprecated */
export const advanceTime = _hootDom.advanceTime;
/** @deprecated */
export const animationFrame = _hootDom.animationFrame;
/** @deprecated */
export const cancelAllTimers = _hootDom.cancelAllTimers;
/** @deprecated */
export const Deferred = _hootDom.Deferred;
/** @deprecated */
export const delay = _hootDom.delay;
/** @deprecated */
export const freezeTime = _hootDom.freezeTime;
/** @deprecated */
export const microTick = _hootDom.microTick;
/** @deprecated */
export const runAllTimers = _hootDom.runAllTimers;
/** @deprecated */
export const setFrameRate = _hootDom.setFrameRate;
/** @deprecated */
export const tick = _hootDom.tick;
/** @deprecated */
export const unfreezeTime = _hootDom.unfreezeTime;

/** @deprecated */
export const disableAnimations = _animation.disableAnimations;
/** @deprecated */
export const enableTransitions = _animation.enableTransitions;

/** @deprecated */
export const mockDate = _date.mockDate;
/** @deprecated */
export const mockLocale = _date.mockLocale;
/** @deprecated */
export const mockTimeZone = _date.mockTimeZone;
/** @deprecated */
export const onTimeZoneChange = _date.onTimeZoneChange;

/** @deprecated */
export const makeSeededRandom = _math.makeSeededRandom;

/** @deprecated */
export const mockPermission = _navigator.mockPermission;
/** @deprecated */
export const mockSendBeacon = _navigator.mockSendBeacon;
/** @deprecated */
export const mockUserAgent = _navigator.mockUserAgent;
/** @deprecated */
export const mockVibrate = _navigator.mockVibrate;

/** @deprecated */
export const mockFetch = _network.mockFetch;
/** @deprecated */
export const mockLocation = _network.mockLocation;
/** @deprecated */
export const mockWebSocket = _network.mockWebSocket;
/** @deprecated */
export const mockWorker = _network.mockWorker;

/** @deprecated */
export const flushNotifications = _notification.flushNotifications;

/** @deprecated */
export const mockMatchMedia = _window.mockMatchMedia;
/** @deprecated */
export const mockTouch = _window.mockTouch;
/** @deprecated */
export const watchAddedNodes = _window.watchAddedNodes;
/** @deprecated */
export const watchKeys = _window.watchKeys;
/** @deprecated */
export const watchListeners = _window.watchListeners;
