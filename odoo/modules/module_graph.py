"""Modules dependency graph."""

import functools
import logging
import typing
from typing import Literal

from odoo.tools import OrderedSet, reset_cached_properties
from odoo.tools.sql import column_exists

from .module import Manifest

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping

    from odoo.db import BaseCursor

    STATES = Literal[
        "uninstallable",
        "uninstalled",
        "installed",
        "to upgrade",
        "to remove",
        "to install",
    ]

_logger = logging.getLogger(__name__)


# THE LOADING ORDER
#
# Dependency Graph:
#      +---------+
#      |  base   |
#      +---------+
#        ^
#        |
#        |
#      +---------+
#      | module1 | <-----+
#      +---------+       |
#        ^               |
#        |               |
#        |               |
#      +---------+     +---------+
#   +> | module2 |     | module3 |
#   |  +---------+     +---------+
#   |    ^               ^     ^
#   |    |               |     |
#   |    |               |     |
#   |  +---------+       |     |  +---------+
#   |  | module4 | ------+     +- | module5 |
#   |  +---------+                +---------+
#   |    ^
#   |    |
#   |    |
#   |  +---------+
#   +- | module6 |
#      +---------+
#
#
# We always load module base in the zeroth phase, because
# 1. base should always be the single drain of the dependency graph
# 2. we need to use models in the base to upgrade other modules
#
# If the ModuleGraph is in the 'load' mode
# all non-base modules are loaded in the same phase
# the loading order of modules in the same phase are sorted by the (depth, order_name)
# where depth is the longest distance from the module to the base module along the dependency graph.
# For example: the depth of module6 is 4 (path: module6 -> module4 -> module2 -> module1 -> base)
# As a result, the loading order is
# phase 0: base
# phase 1: module1 -> module2 -> module3 -> module4 -> module5 -> module6
#
# If the ModuleGraph is in the 'update' mode
# For example,
# 'installed' : base, module1, module2, module3
# 'to upgrade': module4, module6
# 'to install': module5
# the updating order is
# phase 0: base
# phase 1: module1 -> module2 -> module3 -> module4 -> module6
# phase 2: module5
#
# In summary:
# phase 0: base
# phase odd: (modules: 1. don't need init; 2. all depends modules have been loaded or going to be loaded in this phase)
# phase even: (modules: 1. need init; 2. all depends modules have been loaded or going to be loaded in this phase)
#
#
# Test modules
# For a module starting with 'test_', we want it to be loaded right after its last loaded dependency in the 'load' mode,
# let's call that module 'xxx'.
# Therefore, the depth will be 'xxx.depth' and the name will be prefixed by 'xxx ' as its order_name.
#
#
# Corner case
# Sometimes the dependency may be changed for sake of upgrade
# For example
#      BEFORE UPGRADE                                       UPGRADING
#
#      +---------+                                          +---------+
#      |  base   |                                          |  base   |
#      +---------+                                          +---------+
#        ^   installed                                        ^    to upgrade
#        |                                                    |
#        |                                                    |
#      +---------+                                          +---------+
#      | module1 |                                          | module1 | <-----+
#      +---------+                                          +---------+       |
#        ^   installed                                        ^    to upgrade |
#        |                         ==>                        |               |
#        |                                                    |               |
#      +---------+                                          +---------+     +---------+
#      | module2 |                                          | module2 |     | module3 |
#      +---------+                                          +---------+     +---------+
#        ^   installed                                        ^    to upgrade ^    to install
#        |                                                    |               |
#        |                                                    |               |
#      +---------+                                          +---------+       |
#      | module4 |                                          | module4 | ------+
#      +---------+                                          +---------+
#            installed                                             to upgrade
#
# Because of the new dependency module4 -> module3
# The module3 will be marked 'to install' while upgrading, and module4 should be loaded after module3
# As a result, the updating order is
# phase 0: base
# phase 1: module1 -> module2
# phase 2: module3
# phase 3: module4


class ModuleNode:
    """Loading and upgrade info for an Odoo module: manifest, DB state, load
    state, and dependency edges."""

    def __init__(self, name: str, module_graph: ModuleGraph) -> None:
        # manifest data
        self.name: str = name
        # for performance reasons, use the cached value to avoid deepcopy; it is
        # acceptable in this context since we don't modify it
        manifest = Manifest.for_addon(name, display_warning=False)
        if manifest is not None:
            # Parse the manifest now so validation errors surface during graph
            # construction instead of mid-loading-loop.
            manifest._force_parse()
        self.manifest: Mapping = manifest or {}

        # ir_module_module data                     # column_name
        self.id: int = 0  # id
        self.state: STATES = "uninstalled"  # state
        self.demo: bool = False  # demo
        self.db_version: str | None = None  # db_version

        # info for upgrade
        self.load_state: STATES = "uninstalled"  # the state when added to module_graph
        self.load_version: str | None = None  # the version when added to module_graph

        # dependency
        self.depends: OrderedSet[ModuleNode] = OrderedSet()
        self.module_graph: ModuleGraph = module_graph

    @functools.cached_property
    def order_name(self) -> str:
        if self.name.startswith("test_"):
            # The 'space' was chosen because it's smaller than any character that can be used by the module name.
            last_installed_dependency = max(
                self.depends, key=lambda m: (m.depth, m.order_name)
            )
            return last_installed_dependency.order_name + " " + self.name

        return self.name

    @functools.cached_property
    def depth(self) -> int:
        """Return the longest distance from self to module 'base' along dependencies."""
        if self.name.startswith("test_"):
            last_installed_dependency = max(
                self.depends, key=lambda m: (m.depth, m.order_name)
            )
            return last_installed_dependency.depth

        return max(module.depth for module in self.depends) + 1 if self.depends else 0

    @functools.cached_property
    def phase(self) -> int:
        if self.name == "base":
            return 0

        if self.module_graph.mode == "load":
            return 1

        def not_in_the_same_phase(module: ModuleNode, dependency: ModuleNode) -> bool:
            return (module.state == "to install") ^ (dependency.state == "to install")

        return max(
            dependency.phase
            + (1 if not_in_the_same_phase(self, dependency) else 0)
            + (1 if dependency.name == "base" else 0)
            for dependency in self.depends
        )

    @property
    def demo_installable(self) -> bool:
        return all(p.demo for p in self.depends)


class ModuleGraph:
    """Odoo modules sorted by (module.phase, module.depth, module.order_name)."""

    def __init__(
        self, cr: BaseCursor, mode: Literal["load", "update"] = "load"
    ) -> None:
        # mode 'load': for simply loading modules without updating them
        # mode 'update': for loading and updating modules
        self.mode: Literal["load", "update"] = mode
        self._modules: dict[str, ModuleNode] = {}
        self._cr: BaseCursor = cr

    def __contains__(self, name: str) -> bool:
        return name in self._modules

    def __getitem__(self, name: str) -> ModuleNode:
        return self._modules[name]

    def __iter__(self) -> Iterator[ModuleNode]:
        return iter(
            sorted(
                self._modules.values(),
                key=lambda p: (p.phase, p.depth, p.order_name),
            )
        )

    def __len__(self) -> int:
        return len(self._modules)

    def extend(self, names: Collection[str]) -> None:
        for module in self._modules.values():
            reset_cached_properties(module)

        names = [name for name in names if name not in self._modules]

        for name in names:
            module = self._modules[name] = ModuleNode(name, self)
            if not module.manifest.get("installable"):
                if name in self._imported_modules:
                    self._remove(name, log_dependents=False)
                else:
                    _logger.warning("module %s: not installable, skipped", name)
                    self._remove(name)

        self._update_depends(names)
        self._update_depth(names)
        self._update_from_database(names)

    @functools.cached_property
    def _imported_modules(self) -> OrderedSet[str]:
        # "studio_customization" is an imported module with no addon directory,
        # so it is not discoverable from the addons path.
        result = ["studio_customization"]
        if column_exists(self._cr, "ir_module_module", "imported"):
            self._cr.execute("SELECT name FROM ir_module_module WHERE imported")
            result += [m[0] for m in self._cr.fetchall()]
        return OrderedSet(result)

    def _update_depends(self, names: Iterable[str]) -> None:
        for name in names:
            if module := self._modules.get(name):
                depends = module.manifest["depends"]
                try:
                    module.depends = OrderedSet(self._modules[dep] for dep in depends)
                except KeyError:
                    missing = [dep for dep in depends if dep not in self._modules]
                    _logger.warning(
                        "module %s: some depends are not loaded (%s), skipped",
                        name,
                        ", ".join(missing),
                    )
                    self._remove(name)

    def _update_depth(self, names: Iterable[str]) -> None:
        # Detect cycles explicitly via iterative DFS rather than relying on
        # Python's recursion limit: a cycle and a very deep acyclic chain
        # produce the same RecursionError, and the latter would be falsely
        # reported as a dependency loop.
        for cycle_member in self._find_cycle_members():
            if cycle_member in self._modules:
                _logger.warning(
                    "module %s: in a dependency loop, skipped",
                    cycle_member,
                )
                self._remove(cycle_member)
        # With cycles removed, depth recursion is bounded by graph diameter.
        for name in names:
            if module := self._modules.get(name):
                module.depth  # noqa: B018 — force cached_property computation now

    def _find_cycle_members(self) -> set[str]:
        """Return names of modules that participate in any dependency cycle.

        Uses Tarjan's strongly connected components algorithm: a node is on a
        cycle iff it lies in a non-singleton SCC or has a self-loop.  Iterative,
        so it is safe on graphs deeper than Python's recursion limit.
        """
        indices: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        on_scc_stack: set[str] = set()
        scc_stack: list[str] = []
        on_cycle: set[str] = set()
        counter = 0

        def deps_of(name: str) -> list[str]:
            # Filter out dependencies that are not in the graph (they may have
            # been pruned for being missing or non-installable).
            return [
                d.name for d in self._modules[name].depends if d.name in self._modules
            ]

        for root in list(self._modules):
            if root in indices:
                continue
            indices[root] = lowlinks[root] = counter
            counter += 1
            scc_stack.append(root)
            on_scc_stack.add(root)
            # Each work entry: [name, next_dep_idx, deps_list].  Mutable list so
            # we can advance the iterator in place when re-entering this frame.
            work: list[list] = [[root, 0, deps_of(root)]]

            while work:
                name, idx, deps = work[-1]
                if idx < len(deps):
                    work[-1][1] = idx + 1
                    child = deps[idx]
                    if child not in indices:
                        indices[child] = lowlinks[child] = counter
                        counter += 1
                        scc_stack.append(child)
                        on_scc_stack.add(child)
                        work.append([child, 0, deps_of(child)])
                    elif child in on_scc_stack:
                        lowlinks[name] = min(lowlinks[name], indices[child])
                else:
                    # Finished exploring children of `name`.  If lowlink == index
                    # then `name` is the root of an SCC; pop everything above it.
                    if lowlinks[name] == indices[name]:
                        scc: list[str] = []
                        while True:
                            w = scc_stack.pop()
                            on_scc_stack.discard(w)
                            scc.append(w)
                            if w == name:
                                break
                        # Singleton SCC is on a cycle only if it has a self-loop.
                        if len(scc) > 1 or name in deps_of(name):
                            on_cycle.update(scc)
                    work.pop()
                    if work:
                        parent = work[-1][0]
                        lowlinks[parent] = min(lowlinks[parent], lowlinks[name])

        return on_cycle

    def _update_from_database(self, names: Iterable[str]) -> None:
        names = tuple(name for name in names if name in self._modules)
        if not names:
            return
        # update modules with values from the database (if exist)
        query = """
            SELECT name, id, state, demo, db_version
            FROM ir_module_module
            WHERE name = ANY(%s)
        """
        self._cr.execute(query, [list(names)])
        for name, id_, state, demo, db_version in self._cr.fetchall():
            if name not in self._modules:
                # already recursively removed (cascaded via a dependency) while
                # processing an earlier row; skip before _remove()'s unguarded
                # pop() would KeyError on it.
                continue
            if state == "uninstallable":
                _logger.warning("module %s: not installable, skipped", name)
                self._remove(name)
                continue
            if self.mode == "load" and state in ["to install", "uninstalled"]:
                _logger.info("module %s: not installed, skipped", name)
                self._remove(name)
                continue
            module = self._modules[name]
            module.id = id_
            module.state = state
            module.demo = demo
            module.db_version = db_version
            module.load_version = db_version
            module.load_state = state

    def _remove(self, name: str, log_dependents: bool = True) -> None:
        # O(n) scan per removal, but removals are rare (broken/missing modules
        # only), so a reverse-dependency index is not worth its complexity.
        module = self._modules.pop(name)
        for another, another_module in list(self._modules.items()):
            if (
                module in another_module.depends
                and another_module.name in self._modules
            ):
                if log_dependents:
                    _logger.info(
                        "module %s: its direct/indirect dependency is skipped, skipped",
                        another,
                    )
                self._remove(another)
