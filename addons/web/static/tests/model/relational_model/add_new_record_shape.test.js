// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";
import { Group } from "@web/model/relational_model/group";
import { StaticList } from "@web/model/relational_model/static_list";

describe.current.tags("headless");

describe("addNewRecord speaks one vocabulary across the three list-likes", () => {
    test("none of them takes a positional flag any more", () => {
        for (const Class of [StaticList, DynamicRecordList, Group]) {
            if (!Class.prototype.addNewRecord) {
                continue;
            }
            expect(Class.prototype.addNewRecord.length).toBeLessThan(2, {
                message:
                    `${Class.name}.addNewRecord takes more than one parameter — ` +
                    "the second was `atFirstPosition`, and `Group`'s first was a " +
                    "placeholder every caller passed `{}`",
            });
        }
    });

    test("Group no longer carries the discarded first parameter", () => {
        expect(Group.prototype.addNewRecord.length).toBe(0, {
            message:
                "an options object with a default is arity 0; a leading " +
                "`_unused` would make it 1",
        });
    });

    test("addExistingRecord takes the same options object, not a boolean", () => {
        expect(DynamicRecordList.prototype.addExistingRecord.length).toBe(1);
        expect(Group.prototype.addExistingRecord.length).toBe(1);
    });

    test("control: the classes really do all declare it", () => {
        expect([
            typeof StaticList.prototype.addNewRecord,
            typeof DynamicRecordList.prototype.addNewRecord,
            typeof Group.prototype.addNewRecord,
        ]).toEqual(["function", "function", "function"], {
            message:
                "the arity assertions above pass vacuously if a class stops " +
                "declaring the method",
        });
    });
});
