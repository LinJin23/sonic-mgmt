import logging

logger = logging.getLogger(__name__)

CONTAINER_NAME = "aznsa"


def is_aznsa_container_running(duthost):
    """Return True if the aznsa container reports a running status."""
    out = duthost.shell(
        "docker ps --filter name={} --filter status=running -q".format(
            CONTAINER_NAME
        ),
        module_ignore_errors=True,
    )
    return bool(out.get("stdout", "").strip())


def get_aznsa_container_image(duthost):
    """Return the image used by the deployed aznsa container.

    The container is expected to have been deployed by container_upgrade.
    Returns None if the container is not present so the caller can skip.
    """
    inspect = duthost.shell(
        r"docker inspect --format \{\{.Config.Image\}\} " + CONTAINER_NAME,
        module_ignore_errors=True,
    )
    if inspect.get("rc") == 0 and inspect.get("stdout", "").strip():
        return inspect["stdout"].strip()
    return None


def dump_aznsa_container_logs(duthost):
    """Dump the aznsa container logs and inspect output for post-mortem
    diagnostics so a failure is actionable without re-running the test.
    """
    logs = duthost.shell(
        "docker logs --tail 100 {}".format(CONTAINER_NAME),
        module_ignore_errors=True,
    )
    logger.error(
        "aznsa container logs (tail 100):\nstdout:\n%s\nstderr:\n%s",
        logs.get("stdout", ""), logs.get("stderr", ""),
    )
    inspect = duthost.shell(
        "docker inspect {}".format(CONTAINER_NAME),
        module_ignore_errors=True,
    )
    logger.error("aznsa container inspect:\n%s", inspect.get("stdout", ""))
