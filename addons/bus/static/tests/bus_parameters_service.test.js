import { busParametersService } from "@bus/bus_parameters_service";
import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { session } from "@web/session";

describe.current.tags("desktop");

test("serverURL defaults to window.origin", () => {
    // No websocket_gevent_port in session → plain window.origin is used.
    // This covers: threaded mode (workers=0) and proxy mode (proxy_mode=True).
    const result = busParametersService.start();
    expect(result.serverURL).toBe(window.origin);
});

test("serverURL uses gevent port when session.websocket_gevent_port is set", () => {
    // Prefork mode without a reverse proxy: server sets websocket_gevent_port=8072
    // in session info so the client connects to the EventServer instead of the
    // HTTP prefork workers, which cannot serve WebSocket.
    patchWithCleanup(session, { websocket_gevent_port: 8072 });
    const result = busParametersService.start();
    const url = new URL(result.serverURL);
    expect(url.port).toBe("8072");
    // Host and protocol should be preserved from window.origin.
    const origin = new URL(window.origin);
    expect(url.hostname).toBe(origin.hostname);
    expect(url.protocol).toBe(origin.protocol);
});

test("serverURL is unchanged when websocket_gevent_port is falsy", () => {
    // 0 and undefined are both falsy — neither should trigger a port swap.
    patchWithCleanup(session, { websocket_gevent_port: 0 });
    expect(busParametersService.start().serverURL).toBe(window.origin);

    patchWithCleanup(session, { websocket_gevent_port: undefined });
    expect(busParametersService.start().serverURL).toBe(window.origin);
});
