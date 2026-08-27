/** @odoo-module native */

// Fixture for TestBridgeExportResolverReadsDisk: a generic ESM resolver
// test needs *some* real module exposing both a named const and a named
// class export, but it should not depend on web/core/registry.js's actual
// shape -- a rename inside web has nothing to do with the resolver's own
// correctness. Mirrors the export names web/core/registry.js happens to
// use only because that made the original test's intent easy to keep.
//
// Addressed by DIRECTORY (like the sibling faced/ fixture), not as a flat
// native_esm/registry.js file: test_assetsbundle.native_esm's manifest
// bundle globs native_esm/*.js, and a flat file here would silently join
// that bundle's member list.
export const registry = {};

export class Registry {}
