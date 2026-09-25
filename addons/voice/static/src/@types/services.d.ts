declare module "services" {
    import { voiceService } from "@voice/voice_service";

    export interface Services {
        voice: typeof voiceService;
    }
}
