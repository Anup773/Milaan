"""Phase 21 -- the rules & compliance framework (ARCHITECTURE.md §12). Importing this package registers the built-in rule sets."""
from __future__ import annotations

from . import accounting as _accounting  # noqa: F401
from . import auditing as _auditing  # noqa: F401
from . import tax as _tax  # noqa: F401
from . import compliance as _compliance  # noqa: F401
from .registry import (ACTIVE, ANY_FRAMEWORK, CATALOG_ONLY, CHECK_KINDS, COVERAGES, FAMILIES, FEATURES, FULL, INTERNATIONAL, NONE,
                       PARTIAL, RULE_SETS, CheckRef, RuleItem, RuleSet, applicable, catalog, checks_for, get, plain,
                       register_rule_set, unknown_check_references)