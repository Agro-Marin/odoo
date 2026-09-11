declare module "registries" {
    interface TourStep {
        content?: string | import("@odoo/owl").Markup;
        trigger?: string;
        run?:
            | string
            | ((
                  helpers: import("@web_tour/js/tour_automatic/tour_helpers").TourHelpers,
              ) => void | Promise<void>);
        [key: string]: any;
    }

    export interface ToursRegistryShape {
        test?: boolean;
        url?: string;
        steps(): TourStep[];
    }

    export interface GlobalRegistryCategories {
        "web_tour.tours": ToursRegistryShape;
    }
}
