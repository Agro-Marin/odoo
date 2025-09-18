// @ts-check

// Re-export useRecordObserver from its canonical location in the fields layer.
// Addons and enterprise modules import from this path — keep the re-export for
// backward compatibility.
export { useRecordObserver } from "@web/fields/hooks/record_observer";
