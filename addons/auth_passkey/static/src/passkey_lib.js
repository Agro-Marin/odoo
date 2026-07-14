/** @odoo-module native */
import { startAuthentication, startRegistration } from "../lib/simplewebauthn.js";

/**
 * Mutable indirection over the vendored simplewebauthn library.
 *
 * Native ES module namespace objects are immutable, so `patch()`ing the
 * library module itself throws ("Cannot redefine property"). Product code
 * calls the WebAuthn entry points through this plain object so test tours
 * can substitute them with fixtures.
 */
export const passkeyLib = { startAuthentication, startRegistration };
