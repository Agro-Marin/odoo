/** @odoo-module native */

// Fixture for TestBridgeExportResolverReadsDisk: a generic ESM resolver
// test needs *some* real module exposing both a named const and a named
// class export, but it should not depend on web/core/registry.js's actual
// shape -- a rename inside web has nothing to do with the resolver's own
// correctness. Mirrors the export names web/core/registry.js happens to
// use only because that made the original test's intent easy to keep.
export const registry = {};

export class Registry {}
