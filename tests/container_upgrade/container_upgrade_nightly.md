# Container Upgrade Nightly Test — Developer Guide

A nightly KVM pipeline that exercises SONiC container upgrades. For a given
service container (e.g. telemetry, restapi, acms), the test:

1. Boots a KVM testbed with a base SONiC image
2. Upgrades the DUT OS to a target version
3. Pulls and starts the target container image on the upgraded DUT
4. Runs the container's testcase suite against it
5. Captures artifacts (cores, output logs, syslog snapshots) for failures

The goal: catch container upgrade regressions for any main service container
across multiple SONiC OS versions, every night, without using physical
hardware.

---

## Where the pieces live

```
.azure-pipelines/
└── container_upgrade_nightly/
    └── container_upgrade_nightly_kvm.yml         ← the pipeline (cron + matrix)

tests/container_upgrade/
├── test_container_upgrade_nightly.py             ← the test wrapper
├── container_upgrade_helper.py                   ← shared helpers
├── parameters.json                               ← per-container docker run flags
├── output_capture_supervisord.conf.template      ← supervisord override
│                                                  ({program} placeholder)
│
├── <service>_container_upgrade_nightly.json      ← per-service nightly config
└── <service>_testcases.json                      ← per-service testcase list
```

---

## Running the pipeline

### From the Azure DevOps pipeline UI

1. Navigate to **Container_Upgrade_Nightly_KVM** in ADO.
2. **Run pipeline** → choose your branch (typically `internal`).
3. Optional parameter overrides:
   - `MGMT_BRANCH` — branch of `sonic-mgmt-int` to run from
   - `CONTAINERS` — list of `{name, config, os_versions, container_override}`
     entries; `os_versions` is comma-separated, one job per
     container × os_version; `container_override` (optional) replaces the
     bundle in the per-service JSON
   - `KVM_IMAGE_BRANCH` — base SONiC image to boot the KVM with (defaults to
     `internal`; the test then `os_upgrade`s to each target version)
   - `MAX_RUN_TEST_MINUTES` — per-job timeout (default 240)
   - `SKIP_PRE_POST_TEST` — skip elastictest pre/post hooks (default `false`)

### From the command line (local debug run)

```bash
cd tests/
python3 -m pytest container_upgrade/test_container_upgrade_nightly.py \
    --inventory=../ansible/veos_vtb \
    --testbed=vms-kvm-t0 \
    --testbed_file=../ansible/vtestbed.yaml \
    --host-pattern=vlab-01 \
    --topology=t0,any --device_type=vs \
    --nightly_config=container_upgrade/<service>_container_upgrade_nightly.json \
    --os_versions=20241212.56 \
    --containers=docker-<service>:<tag> \
    --allow_recover --skip_sanity --disable_loganalyzer
```

Required CLI params:

| flag | purpose |
|---|---|
| `--nightly_config` | path to the `<service>_container_upgrade_nightly.json` |
| `--os_versions` | single OS version to test against (e.g. `20241212.56`) |

Optional:

| flag | purpose |
|---|---|
| `--containers` | override bundle: comma-separated `name:tag,name:tag,...` (commas because `\|` collides with bash; the wrapper converts to pipes internally) |

---

## Reading the results

### Did it pass?

Check the pipeline job summary or the run's artifact tree:

- **`test_container_upgrade_nightly.log`** — outer pytest log
- **`test_container_upgrade_nightly.xml`** — JUnit XML
- **`test_container_upgrade_nightly_output.log`** — full stdout of the outer test

A job **passes** when every testcase in the testcase list returns `True`. The
outer test calls `pytest.fail()` with a summary if any failed.

A job **fails** when:

- Any inner testcase returned `False`
- The OS upgrade failed
- The image couldn't be pulled
- A required setup step errored

### Artifact tree (per job)

| artifact | what's in it | when produced |
|---|---|---|
| `<program>.output.log` | full supervisord stdout+stderr capture for the container's main program (KVM only) | end of run |
| `cores.tar.gz.b64` | base64-encoded tar of every core in `/var/core/` on the DUT (ASCII so it survives elastictest's binary-mangling pipeline) | end of run if any cores exist |
| `<testcase>_<osver>.log` / `.xml` | per-testcase pytest log + JUnit | per testcase |
| `<testcase>_<osver>_var_log.tar.gz` | DUT `/var/log` snapshot at failure | per testcase, only on failure |

**`<program>.output.log` is usually the most useful single artifact** — it
contains every line the program produced via supervisord (including any
panic or fatal error it printed before exit), captured to a host-mounted
file that bypasses syslog and survives container recreates.

---

## Adding a new testcase to an existing service

Each service has a `<service>_testcases.json` file that lists pytest
selectors. To add a testcase:

1. Add the test under `tests/<service>/` like any normal SONiC test.
2. Open the relevant `<service>_testcases.json` and add an entry:
   ```json
   {
     "<service>/test_<service>.py::test_existing_case": "",
     "<service>/test_<service>_my_new_test.py::test_thing": ""
   }
   ```
3. The value (currently empty string) is an optional extra arg passed to
   that test — rarely used, leave empty unless you need it.
4. Commit. The next nightly picks it up.

---

## Adding a new service nightly (new container)

To add `myservice` to the nightly matrix:

1. **Per-service nightly config:** create
   `tests/container_upgrade/myservice_container_upgrade_nightly.json`:
   ```json
   {
     "containers": "docker-myservice:kubelatest-amd64",
     "testcase_file": "container_upgrade/myservice_testcases.json",
     "parameters_file": "container_upgrade/parameters.json",
     "optional_parameters": "-e IS_V1_ENABLED=true"
   }
   ```

2. **Testcase list:** create `tests/container_upgrade/myservice_testcases.json`.

3. **Docker run parameters:** in `parameters.json`, add an entry for the
   container image:
   ```json
   "docker-myservice": {
     "parameters": [
       "--privileged",
       "--pid=host",
       "-v /etc/sonic:/etc/sonic:ro"
     ]
   }
   ```

4. **Output capture (recommended):** in `test_container_upgrade_nightly.py`,
   add to `CONTAINER_TO_PROGRAM`:
   ```python
   CONTAINER_TO_PROGRAM = {
       ...
       "docker-myservice": "myservice",   # ← new entry
   }
   ```
   The test will auto-create `/var/log/myservice-output/myservice.output.log`
   on the DUT and fetch it as an artifact (KVM only). Sidecars and
   watchdogs are implicitly skipped — they're not in this map.

5. **Pipeline matrix:** in `container_upgrade_nightly_kvm.yml`, add an
   entry under `CONTAINERS`:
   ```yaml
   - name: myservice
     config: container_upgrade/myservice_container_upgrade_nightly.json
     os_versions: "20241212.56,20250510.30"
   ```

---

## KVM testbed vs. physical testbed

This nightly **runs on KVM only**. Physical container_upgrade tests live in
the separate `test_container_upgrade.py`. Differences to be aware of:

| area | KVM | Physical |
|---|---|---|
| Network reachability | DUT (vlab-01) is on a private bridge `10.250.0.0/24`; **cannot reach the internet, the container registry, or `sonic.packages.trafficmanager.net`** | full network access |
| How images reach the DUT | `pull_run_dockers` pulls on the test runner (sonic-mgmt container), `docker save` → tar, `duthost.copy` to DUT, `docker load` | DUT pulls directly from registry |
| OS upgrade image transfer | localhost downloads the `.bin`, copies to DUT, `sonic-installer install`, reboot | DUT downloads directly |
| Hardware-dependent tests (sensors, PSU, FAN, optics, link flap) | mostly skipped (no real hardware to read) | run for real |
| ASIC type | `vs` (virtual switch) — limited SAI features | real ASIC |
| DPU / chassis / multi-ASIC | single-line-card single-ASIC only | real chassis behavior |
| Container lifecycle | `IS_V1_ENABLED=true` is set in `optional_parameters` so the host's `/usr/bin/<service>.sh` (sed-injected by `migrate_container_systemd`) drives the container — same flow as non-kube physical boxes | same flow on non-kube physical boxes |
| Output capture (`<program>.output.log`) | enabled (bind-mounted supervisord override) | not applied; physical relies on `/var/log/<program>.log` directly |

**Practical implication:** testcases that need real hardware (sensor reads,
PSU stress, real optics, link flap with real SFP) **should not** be added
to the nightly testcase list. They will either skip noisily or fail.

---

## Debugging when a test fails

When a job fails, work through these in order. Most issues are diagnosed
from the first two artifacts.

### 1. Check what failed

`test_container_upgrade_nightly_output.log` ends with the test results
dict, e.g.:

```
{'20241212_56': {
  '<service>_test_<service>::test_config_db_parameters': True,
  ...
  '<service>_test_<service>_<some_case>::test_thing': False,
}}
'dut_check_result': {'config_db_check_failed': False, 'core_dump_check_failed': True}
```

`core_dump_check_failed: True` means a new core appeared in `/var/core/` on
the DUT during the run — something inside the container crashed.

### 2. Read `<program>.output.log` first

This is the **full output of the container's main program** across every
restart in the run, captured via a bind-mounted supervisord override that
bypasses the syslog chain and survives container recreates. Grep it for
the obvious crash markers for your runtime — panic strings, fatal errors,
abort messages, signal names.

```bash
grep -E "panic:|fatal error:|abort|signal SIG|assertion|exit status" <program>.output.log
```

If the program printed anything before dying, **it's here**, with full
multi-line traces intact (file routing does not have the per-message size
limit or rate limit that the syslog path has).

### 3. If `<program>.output.log` doesn't have the answer

Look at the per-testcase artifacts to identify *when* the failure happened
and what the DUT host was doing around then:

- `<testcase>_<osver>.log` — pytest log for the testcase that failed
- `<testcase>_<osver>_var_log.tar.gz` — full DUT `/var/log` snapshot taken
  at the moment the testcase failed
  ```bash
  tar -xzf <testcase>_<osver>_var_log.tar.gz -C /tmp/var_log
  ls /tmp/var_log/
  # Useful contents:
  #   syslog            — host syslog around the failure
  #   <program>.log     — host's filtered per-program syslog
  #   kern.log          — kernel log (OOM, signal, etc.)
  #   auth.log          — auth/login events
  ```

Useful host-syslog patterns when the container is restart-looping:

```bash
grep -E "<service>\.service: Found left-over process|Deactivated successfully|Scheduled restart" /tmp/var_log/syslog
# ↑ shows the systemd restart-loop pattern
```

### 4. Cores as a last resort

If the program crashed in a way that didn't produce any output (very early
init crash, externally-delivered signal, etc.), `cores.tar.gz.b64` has
every core dump from `/var/core/` on the DUT, base64-encoded so it survives
the artifact pipeline:

```bash
base64 -d cores.tar.gz.b64 | tar -xzf -
ls *.core.gz
```

Analyzing a core to recover a stack trace is runtime-specific and
out of scope for this guide — it generally needs the matching binary, with
debug symbols, and a runtime-specific debugger. Talk to the relevant
service owner.

---

## Common gotchas

| symptom | likely cause |
|---|---|
| `<program>.output.log` exists but is empty | The program never reached any output statement (instant startup crash) **or** an external signal killed it before any output flushed. Use the core dump (§4) for that case. |
| No artifacts at all besides the outer 3 files | elastictest's `collect_dump.py` failed (common after an `os_upgrade`). The artifacts that *do* exist are the ones the test fetches itself; if those are also missing, the test errored before reaching the end-of-run capture block. |
| `<service> container is not running` in a testcase log | The container is in a restart-loop. Check `<program>.output.log` for the crash, and `<testcase>_var_log.tar.gz/syslog` for the `Deactivated successfully` / `Found left-over process` cycle. |
| Tests pass on physical but fail on KVM | A hardware-dependent test got added to the nightly testcase list. Move it back to a physical-only suite. |
| `cores.tar.gz.b64` won't decode cleanly | Your download mangled it (some browser previews UTF-8-decode binary text). Use `curl -o` / `wget` / "Save link as", then `base64 -d`. |

---

## Reference: what `pull_run_dockers` actually does

For each container in the nightly bundle:

1. Pull the image on `localhost` (the sonic-mgmt test runner).
2. `docker save` → tar, `duthost.copy` to DUT, `docker load`.
3. `docker stop` + `docker rm` the existing container of that name on the DUT.
4. `docker tag <pulled_image> <container_name>:latest`.
5. If `IS_V1_ENABLED=true` is in `optional_parameters` and the container is
   not a sidecar/watchdog: `migrate_container_systemd(duthost, service,
   parameters)` is called. It **sed-injects the parameters from
   `parameters.json` into the host's `/usr/bin/<service>.sh` docker create
   line**, then `systemctl restart`s the service. The KVM output-capture
   bind mounts are injected here too.
6. Otherwise: a plain `docker run -d <params> --name <container_name>
   <image>` is issued.

This explains why changes to `parameters.json` take effect: they get
sed-baked into `/usr/bin/<service>.sh` on the host, and every subsequent
restart of that systemd unit uses the new docker create line.
