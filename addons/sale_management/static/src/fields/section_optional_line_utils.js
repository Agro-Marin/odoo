/** @odoo-module native */
import { getSectionRecords } from "@account/components/section_and_note_fields_backend/section_and_note_fields_backend";
import { x2ManyCommands } from "@web/core/network";
import { listId } from "@web/model/relational_model";

/**
 * Builds a map of records whose optional state needs to be recomputed
 * after a record is moved within the list.
 *
 * The map’s keys are record IDs, and values represent their current
 * `is_optional` collapse state as determined by `shouldCollapse()`.
 *
 * Shared between `SaleOrderLineListRenderer` (sale_order_line_field.js) and
 * `SaleOrderTemplateLineListRenderer` (sale_order_template_line_field.js):
 * the two renderers had this method byte-for-byte identical.
 *
 * @param {Object} renderer - The list renderer instance (`this` of the caller).
 * @param {Object} record - The record being moved.
 * @param {number|string} targetId - The ID of the record that serves as the new drop target.
 * @returns {Map<number|string, boolean>} A map of record IDs to their recomputed optional states.
 */
export function getRecordsToRecompute(renderer, record, targetId) {
    const optionalStateMap = new Map();

    if (renderer.isSection(record)) {
        // If a section or subsection is moved
        let currentIndex = renderer.props.list.records.findIndex(
            (r) => r.id === record.id,
        );
        let targetIndex = renderer.props.list.records.findIndex(
            (r) => r.id === targetId,
        );
        if (currentIndex > targetIndex) {
            //When moving up, recompute:
            // 1. All records under the moved section.
            // 2. All records between the new and old positions.
            for (let i = currentIndex; i > targetIndex; i--) {
                if (!renderer.props.list.records[i].data.display_type) {
                    optionalStateMap.set(
                        renderer.props.list.records[i].id,
                        renderer.shouldCollapse(
                            renderer.props.list.records[i],
                            "is_optional",
                        ),
                    );
                }
            }
            for (const sectionRecord of getSectionRecords(
                renderer.props.list,
                record,
            )) {
                if (!sectionRecord.data.display_type) {
                    optionalStateMap.set(
                        sectionRecord.id,
                        renderer.shouldCollapse(sectionRecord, "is_optional"),
                    );
                }
            }
        } else {
            //When moving down, recompute:
            // 1. All records under sections between the old and new positions.
            // 2. All records between the old and new positions (skipping overlaps).
            for (let i = currentIndex; i <= targetIndex; i++) {
                if (renderer.isSection(renderer.props.list.records[i])) {
                    for (const sectionRecord of getSectionRecords(
                        renderer.props.list,
                        renderer.props.list.records[i],
                    )) {
                        if (
                            !optionalStateMap.has(sectionRecord.id) &&
                            !sectionRecord.data.display_type
                        ) {
                            optionalStateMap.set(
                                sectionRecord.id,
                                renderer.shouldCollapse(sectionRecord, "is_optional"),
                            );
                        }
                    }
                }

                // we must skip overlapping records
                if (
                    !optionalStateMap.has(renderer.props.list.records[i].id) &&
                    !renderer.props.list.records[i].data.display_type
                ) {
                    optionalStateMap.set(
                        renderer.props.list.records[i].id,
                        renderer.shouldCollapse(
                            renderer.props.list.records[i],
                            "is_optional",
                        ),
                    );
                }
            }
        }
    } else if (!record.data.display_type) {
        // If a regular record is moved compute its own optional state
        optionalStateMap.set(
            record.id,
            renderer.shouldCollapse(record, "is_optional"),
        );
    }

    return optionalStateMap;
}

/**
 * Applies the quantity adjustments implied by a drag/drop optional-state
 * change: a product line entering an optional section gets qty 0, and one
 * leaving it (with qty still 0) gets reset to 1.
 *
 * Shared between the same two renderers as `getRecordsToRecompute` above.
 *
 * @param {Object} renderer - The list renderer instance (`this` of the caller).
 * @param {Map<number|string, boolean>} recordMap - As returned by `getRecordsToRecompute`.
 */
export async function handleQuantityAdjustment(renderer, recordMap) {
    const commands = [];

    for (const [recordId, wasOptional] of recordMap.entries()) {
        const record = renderer.props.list.records.find((r) => r.id === recordId);
        const isOptional = renderer.shouldCollapse(record, "is_optional");

        if (wasOptional && !isOptional && !record.data.product_uom_qty) {
            commands.push(
                x2ManyCommands.update(listId(record), {
                    product_uom_qty: 1,
                }),
            );
        } else if (!wasOptional && isOptional) {
            commands.push(
                x2ManyCommands.update(listId(record), {
                    product_uom_qty: 0,
                }),
            );
        }
    }

    await renderer.props.list.applyCommands(commands, { sort: true });
}
