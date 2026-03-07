import { registry } from "@web/core/registry";
import { session } from "@web/session";

export const busParametersService = {
    start() {
        // In prefork mode without a reverse proxy the server exposes the
        // gevent port so the client connects to the EventServer (port 8072)
        // instead of the HTTP prefork workers, which cannot serve WebSocket.
        let serverURL = window.origin;
        if (session.websocket_gevent_port) {
            const url = new URL(window.origin);
            url.port = session.websocket_gevent_port;
            serverURL = url.origin;
        }
        return { serverURL };
    },
};

registry.category("services").add("bus.parameters", busParametersService);
