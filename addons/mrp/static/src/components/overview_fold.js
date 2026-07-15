/** @odoo-module native */
import { useEnv } from "@odoo/owl";
import { useBus } from "@web/core/utils/hooks";

/**
 * Shared fold protocol for the BoM Overview and MO Overview component trees.
 *
 * Both trees are report tables whose rows can be folded/unfolded. They render
 * different data, but the folding plumbing is identical and now goes through a
 * single channel: the `overviewBus` placed in the sub-env by each root.
 *
 * Events:
 *   FOLD_CHANGED { ids: string[], folded: boolean }
 *       A block's fold state changed. The root keeps its `unfoldedIds` set in
 *       sync so the printed PDF reproduces the on-screen fold state.
 *   FOLD_ALL { folded: boolean }
 *       Fold or unfold every block at once (the control-panel button).
 */
export const FOLD_CHANGED = "fold-changed";
export const FOLD_ALL = "fold-all";

/**
 * Root-side hook: return a Set of the currently-unfolded line ids, kept in sync
 * with the FOLD_CHANGED events emitted by the blocks. That set is what the
 * report URL uses to reproduce the on-screen fold state in the PDF.
 *
 * Must be called after the root has installed `overviewBus` via useSubEnv.
 */
export function useUnfoldedIds() {
    const env = useEnv();
    const unfoldedIds = new Set();
    useBus(env.overviewBus, FOLD_CHANGED, ({ detail }) => {
        const operation = detail.folded ? "delete" : "add";
        detail.ids.forEach((id) => unfoldedIds[operation](id));
    });
    return unfoldedIds;
}
