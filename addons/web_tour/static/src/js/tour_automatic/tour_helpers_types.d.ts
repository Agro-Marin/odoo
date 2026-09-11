import "@web_tour/js/tour_automatic/tour_helpers";
declare module "@web_tour/js/tour_automatic/tour_helpers" {
    interface TourHelpers {
        click(selector?: string): Promise<void>;
        waitFor: typeof import("@odoo/hoot-dom").waitFor;
        queryFirst: typeof import("@odoo/hoot-dom").queryFirst;
        editor(text: string, selector?: string): Promise<void>;
    }
}
