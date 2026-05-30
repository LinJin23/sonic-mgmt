"""Self-contained BGP aggregate-address helpers for tests/closa/.

This module is a closa-local copy of the symbols originally provided by
``tests/bgp/bgp_aggregate_helpers.py``, plus an *extended* ``AggregateCfg``
named-tuple (with two ``*_prefix_list`` fields) and a matching
``gcu_add_aggregate`` that emits those fields into the CONFIG_DB patch.

Why a copy rather than ``from tests.bgp.bgp_aggregate_helpers import ...``:
  - The repo CI rule ``.azure-pipelines/dependency_check/dependency_check.py``
    forbids cross-feature imports (``tests/closa/*`` may not import from
    ``tests/bgp/*``).
  - The closa policy also forbids modifying public files under
    ``tests/bgp/`` to add the prefix-list fields directly there.
  - The intersection of those two rules forces an in-place copy here.

If the upstream public ``bgp_aggregate_helpers`` ever fixes a bug in
``dump_db`` / ``verify_bgp_aggregate_cleanup`` / etc., this file must be
manually synced.
"""

import ast
import logging
from collections import namedtuple

from tests.common.gcu_utils import apply_gcu_patch
from tests.common.helpers.assertions import pytest_assert
from tests.common.utilities import wait_until

logger = logging.getLogger(__name__)


# ---- Constants (copied verbatim from tests/bgp/bgp_aggregate_helpers.py) ----
BGP_AGGREGATE_ADDRESS = "BGP_AGGREGATE_ADDRESS"
# Use a /24 (not /32) — FRR rejects host-route aggregates with
# 'will not result in any useful aggregation, disallowing'.
# 192.0.2.0/24 is the RFC 5737 TEST-NET-1 documentation block.
PLACEHOLDER_PREFIX = "192.0.2.0/24"

# Convergence wait times
BGP_SETTLE_WAIT = 5


# ---- AggregateCfg ----
# Extended named-tuple: superset of the public 4-field AggregateCfg, adds
# two optional ``*_prefix_list`` fields used by the tier-tagging feature.
# Defaults make it backwards-compatible for callers that only set the
# original 4 fields.
AggregateCfg = namedtuple(
    "AggregateCfg",
    ["prefix", "bbr_required", "summary_only", "as_set",
     "aggregate_prefix_list", "contributing_prefix_list"],
    defaults=(False, False, False, "", ""),
)


# ---- DB & running-config helpers ----
def dump_db(duthost, dbname, tablename):
    """Return current DB content as dict."""
    keys_out = duthost.shell(
        f"sonic-db-cli {dbname} keys '{tablename}*'", module_ignore_errors=True
    )["stdout"]
    logger.info(f"dump {dbname} db, table {tablename}, keys output: {keys_out}")
    keys = keys_out.strip().splitlines() if keys_out.strip() else []
    res = {}
    for k in keys:
        fields = duthost.shell(
            f"sonic-db-cli {dbname} hgetall '{k}'", module_ignore_errors=True
        )["stdout"]
        logger.info(f"all fields:{fields} for key: {k}")
        prefix = k.removeprefix(f"{tablename}|")
        res[prefix] = ast.literal_eval(fields)
    logger.info(f"dump {dbname} table {tablename} result: {res}")
    return res


def running_bgp_has_aggregate(duthost, prefix):
    """Grep FRR running BGP config for aggregate-address lines."""
    return duthost.shell(
        f"show runningconfiguration bgp | grep -i 'aggregate-address {prefix}'",
        module_ignore_errors=True,
    )["stdout"]


# ---- GCU JSON patch helpers ----
def gcu_add_placeholder_aggregate(duthost, prefix):
    patch = [
        {
            "op": "add",
            "path": f"/BGP_AGGREGATE_ADDRESS/{prefix.replace('/', '~1')}",
            "value": {"summary-only": "false", "as-set": "false"},
        }
    ]
    logger.info(f"Adding placeholder BGP aggregate {prefix.replace('/', '~1')}")
    return apply_gcu_patch(duthost, patch)


def _aggregate_value(cfg):
    """Render an extended ``AggregateCfg`` to the CONFIG_DB value dict.

    The two ``*-prefix-list`` fields are omitted when empty so the rendered
    payload matches the public helper exactly when prefix-lists are unused.
    """
    value = {
        "bbr-required": "true" if cfg.bbr_required else "false",
        "summary-only": "true" if cfg.summary_only else "false",
        "as-set":       "true" if cfg.as_set else "false",
    }
    if cfg.aggregate_prefix_list:
        value["aggregate-address-prefix-list"] = cfg.aggregate_prefix_list
    if cfg.contributing_prefix_list:
        value["contributing-address-prefix-list"] = cfg.contributing_prefix_list
    return value


def gcu_add_aggregate(duthost, aggregate_cfg):
    """closa version of ``gcu_add_aggregate`` — emits the prefix-list fields.

    Required because the public helper only knows about the original 4
    ``AggregateCfg`` fields; it would silently drop ``aggregate_prefix_list``
    and ``contributing_prefix_list``.
    """
    logger.info("Add BGP_AGGREGATE_ADDRESS by GCU cmd (closa, with prefix-list fields)")
    patch = [
        {
            "op": "add",
            "path": f"/BGP_AGGREGATE_ADDRESS/{aggregate_cfg.prefix.replace('/', '~1')}",
            "value": _aggregate_value(aggregate_cfg),
        }
    ]
    apply_gcu_patch(duthost, patch)


def gcu_remove_aggregate(duthost, prefix):
    patch = [{"op": "remove", "path": f"/BGP_AGGREGATE_ADDRESS/{prefix.replace('/', '~1')}"}]
    apply_gcu_patch(duthost, patch)


# ---- Common Validators ----
def verify_bgp_aggregate_cleanup(duthost, prefix):
    """Validate aggregate is fully removed from CONFIG_DB, STATE_DB, and FRR running-config."""
    # CONFIG_DB validation
    config_db = dump_db(duthost, "CONFIG_DB", BGP_AGGREGATE_ADDRESS)
    pytest_assert(prefix not in config_db, f"Aggregate row {prefix} should be cleaned up from CONFIG_DB")

    # STATE_DB validation
    def _state_db_prefix_gone():
        sdb = dump_db(duthost, "STATE_DB", BGP_AGGREGATE_ADDRESS)
        return prefix not in sdb

    pytest_assert(
        wait_until(30, 5, 0, _state_db_prefix_gone),
        f"STATE_DB entry for {prefix} should be removed after aggregate cleanup",
    )

    # Running-config validation
    running_config = running_bgp_has_aggregate(duthost, prefix)
    pytest_assert(
        prefix.split("/")[0] not in running_config,
        f"aggregate-address {prefix} should not present in FRR running-config",
    )
