import json
import logging

import odoo.tests

_logger = logging.getLogger(__name__)

BROWSER_ONLY_PROBES = ("component.mount", "rpc.request")

SHARED_PROBES = ("service.start", "service.started")


@odoo.tests.tagged("-at_install", "post_install", "web_observability")
class TestTraceProbes(odoo.tests.HttpCase):
    def test_a_real_boot_records_the_probes_hoot_cannot_see(self):
        expected = BROWSER_ONLY_PROBES + SHARED_PROBES
        self.browser_js(
            "/odoo?odoo-trace=1",
            """
            (async () => {
                try {
                    // The ORM call is what makes `rpc.request` deterministic.
                    // That probe belongs to this set because HOOT mocks the
                    // transport and never fires it -- NOT because a boot is
                    // guaranteed to issue an RPC. On a database carrying only
                    // `base` and `web` the webclient boots to an empty action
                    // list, and every request the page makes is a GET for an
                    // asset, the menus or the translations. The probe then
                    // stays at zero and the failure reads as broken probe
                    // wiring when what actually varied is the installed module
                    // set. Provoking one call asserts the wiring, which this
                    // test owns; `orm.call` reaches `rpc()` unconditionally,
                    // since the rpc cache is opt-in through `orm.cache()`.
                    await odoo.__WOWL_DEBUG__.root.env.services.orm.call(
                        "res.users",
                        "search_count",
                        [[]]
                    );
                    const stats = __odooTraceStats();
                    const expected = %s;
                    const missing = expected.filter((key) => !stats[key]);
                    if (missing.length) {
                        console.error(
                            "probes did not fire: " + missing.join(", ") +
                            " -- recorded: " + JSON.stringify(stats)
                        );
                    } else {
                        console.log("TRACE_READING " + JSON.stringify(stats));
                        console.log("test successful");
                    }
                } catch (error) {
                    console.error("probe reading failed: " + error);
                }
            })();
            """
            % json.dumps(list(expected)),
            "odoo.isReady === true",
            login="admin",
        )

    def test_the_sink_stays_silent_without_the_flag(self):
        self.browser_js(
            "/odoo",
            """
            const stats = __odooTraceStats();
            if (Object.keys(stats).length) {
                console.error(
                    "sink recorded without being armed: " + JSON.stringify(stats)
                );
            } else if (__odooTrace) {
                console.error("__odooTrace armed itself with no flag set");
            } else {
                console.log("test successful");
            }
            """,
            "odoo.isReady === true",
            login="admin",
        )

    def test_what_opening_a_list_view_costs(self):
        self.browser_js(
            "/odoo?odoo-trace=1",
            """
            (async () => {
                try {
                    // Let boot's in-flight RPCs settle BEFORE the reset. Without
                    // this the window straddles them and their RESPONSE events
                    // land in the interaction, which reads as more `rpc.ok` than
                    // `rpc.request` -- 8 against 5 when first measured.
                    await new Promise((resolve) => setTimeout(resolve, 2000));
                    __odooTraceReset();
                    __renderReset();
                    __renderTrace = true;
                    const env = odoo.__WOWL_DEBUG__.root.env;
                    await env.services.action.doAction({
                        type: "ir.actions.act_window",
                        res_model: "res.partner",
                        views: [[false, "list"]],
                    });
                    await new Promise((resolve) => setTimeout(resolve, 2000));
                    __renderTrace = false;
                    console.log(
                        "INTERACTION_TRACE " + JSON.stringify(__odooTraceStats())
                    );
                    console.log(
                        "INTERACTION_RENDERS " + JSON.stringify(__renderStats())
                    );
                    console.log("test successful");
                } catch (error) {
                    console.error("interaction reading failed: " + error);
                }
            })();
            """,
            "odoo.isReady === true",
            login="admin",
        )
