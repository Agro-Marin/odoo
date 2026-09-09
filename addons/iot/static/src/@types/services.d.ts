declare module "services" {
    import { iotHttpService } from "@iot/network_utils/iot_http_service";
    import { iotLongpollingService } from "@iot/network_utils/longpolling";

    export interface Services {
        iot_http: typeof iotHttpService;
        iot_longpolling: typeof iotLongpollingService;
    }
}
