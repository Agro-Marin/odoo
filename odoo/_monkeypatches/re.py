import re


def patch_module() -> None:
    """Raise the compiled-pattern cache from CPython's 512 to 4096.

    Odoo's working set does exceed the stdlib floor -- 872 distinct patterns at
    a `-u base` boot, 1341 over a 3261-test `/base` run -- so the cache does
    evict. The measured saving is nonetheless small: 86.7ms -> 80.4ms of
    compile time per boot, 389.6ms -> 366.6ms per test run. Patterns are
    overwhelmingly compiled once and held in module globals, so an eviction
    rarely costs a recompile.

    Kept because it is one assignment and the numbers point the right way, not
    because it is load-bearing. `_MAXCACHE` is still consulted by `re._compile`
    on 3.14; the second-level `_MAXCACHE2` sits alongside it, not in place of
    it.
    """
    re._MAXCACHE = 4096
