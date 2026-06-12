"""oradeck — OCI registry mirror & artifact copy. Part of the Cognis Neural Suite."""

from oradeck.core import (
    TOOL_NAME,
    TOOL_VERSION,
    OradeckError,
    Ref,
    RegistryClient,
    build_demo_fixture,
    copy_to_store,
    digest_of,
    inspect_store,
    parse_ref,
    plan_mirror,
    push_from_store,
    suggest_mirror_set,
)

__version__ = TOOL_VERSION

__all__ = [
    "TOOL_NAME",
    "TOOL_VERSION",
    "__version__",
    "OradeckError",
    "Ref",
    "RegistryClient",
    "build_demo_fixture",
    "copy_to_store",
    "digest_of",
    "inspect_store",
    "parse_ref",
    "plan_mirror",
    "push_from_store",
    "suggest_mirror_set",
]
