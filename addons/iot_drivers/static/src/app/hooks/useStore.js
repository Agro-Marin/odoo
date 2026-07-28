/** @odoo-module native */

import { useEnv, useState } from "/web/static/lib/owl/owl.es.js";

export default function useStore() {
    const env = useEnv();
    return useState(env.store);
}
