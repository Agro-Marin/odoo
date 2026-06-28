// Module augmentation for the luxon types.
//
// @types/luxon (DefinitelyTyped) declares only named exports, but the bundled
// luxon ESM build (static/lib/luxon/luxon.js) ships a real `export default`
// (the whole library object). @web/core/l10n/luxon re-exports it as `luxon`
// (`export { default as luxon }`) for the rare "whole luxon object" consumers
// (kanban sandbox, etc.).
//
// The leading `import "luxon"` makes THIS FILE a module, so the `declare module`
// below is a module AUGMENTATION that MERGES the default into the existing
// declarations (keeping the named DateTime/Duration/... exports) rather than an
// ambient declaration that would shadow them. The default is typed `any` so the
// dynamic `luxon` consumers are not forced onto the strict named types.
import "luxon";

declare module "luxon" {
    const _default: any;
    export default _default;
}
