"""BaseModel mixins package.

BaseModel (models/base.py) is split across these mixins: each provides one
slice of functionality (CRUD, copy, iteration, traversal, cache, environment,
lifecycle, read, search, read_group, translation, schema, IO, access).
"""

# Core operation mixins
from .access import AccessMixin
from .cache import CacheMixin
from .copy import CopyMixin
from .crud import CrudMixin
from .env import EnvironmentMixin
from .io import IOMixin
from .iteration import IterationMixin
from .lifecycle import LifecycleMixin
from .search import SearchMixin

# Data access mixins
from .read import ReadMixin
from .read_group import ReadGroupMixin
from .schema import SchemaMixin

# Feature mixins
from .translation import TranslationMixin
from .traversal import TraversalMixin

__all__ = [
    "AccessMixin",
    "CacheMixin",
    "CopyMixin",
    # Core operation mixins
    "CrudMixin",
    "EnvironmentMixin",
    "IOMixin",
    "IterationMixin",
    "LifecycleMixin",
    "ReadGroupMixin",
    # Data access mixins
    "ReadMixin",
    "SchemaMixin",
    "SearchMixin",
    # Feature mixins
    "TranslationMixin",
    "TraversalMixin",
]
