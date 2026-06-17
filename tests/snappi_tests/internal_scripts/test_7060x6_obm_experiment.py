"""Run routed full-mesh Snappi/Ixia traffic through selected 7060X6 ports while collecting TH5 OBM counters.
Intended for ad hoc internal debugging from the sonic-mgmt container with Ixia/DUT details supplied via env vars."""

import logging
import os
import re
import time
from ipaddress import ip_interface

import pytest

from tests.common.helpers.assertions import pytest_assert, pytest_require
from tests.common.snappi_tests.port import SnappiPortConfig, SnappiPortType


logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.topology("multidut-tgen", "tgen")]

TARGET_DUT = "STR-7060x6-RDMA-1"
TARGET_PORTS = [
    "Ethernet0",
    "Ethernet1",
    "Ethernet2",
    "Ethernet3",
    "Ethernet24",
    "Ethernet25",
    "Ethernet26",
    "Ethernet27",
]
DEFAULT_SWITCH_MAC = "78:5f:6c:30:d7:c4"
DEFAULT_ARESONE_LOGICAL_PORTS = {
    "1.1": 61,
    "1.2": 62,
    "1.3": 63,
    "1.4": 64,
    "4.1": 85,
    "4.2": 86,
    "4.3": 87,
    "4.4": 88,
}


def _normalized_aresone_breakout_location(location):
    chassis, separator, port = location.rpartition(";")
    if separator != ";" or "." not in port:
        return location

    logical_port = _aresone_logical_port_map().get(port)
    if logical_port is None:
        parent_port, lane = port.split(".", 1)
        logical_port = 57 + (int(parent_port) - 1) * 8 + (int(lane) - 1)
    return "{};{}".format(chassis, logical_port)


def _normalize_selected_port_locations(selected_ports):
    normalized_ports = []
    for port in selected_ports:
        normalized_port = port.copy()
        normalized_port["location"] = _normalized_aresone_breakout_location(port["location"])
        normalized_ports.append(normalized_port)
    return normalized_ports


def _bypass_resource_group_conversion(snappi_api, testbed_config):
    if hasattr(snappi_api, "resource_group") and testbed_config.layer1:
        layer1_names = [layer1.name for layer1 in testbed_config.layer1]
        snappi_api.resource_group.set_group = lambda: layer1_names


def _int_env(name, default):
    value = os.environ.get(name)
    return int(value) if value else default


def _float_env(name, default):
    value = os.environ.get(name)
    return float(value) if value else default


def _aresone_logical_port_map():
    logical_ports = DEFAULT_ARESONE_LOGICAL_PORTS.copy()
    overrides = os.environ.get("OBM_ARESONE_LOGICAL_PORTS", "")
    for override in overrides.split(","):
        if not override.strip():
            continue
        port, _, logical_port = override.partition("=")
        pytest_require(port and logical_port, "Invalid OBM_ARESONE_LOGICAL_PORTS entry: {}".format(override))
        logical_ports[port.strip()] = int(logical_port.strip())
    return logical_ports


def _target_counter_filter():
    ports = "|".join(TARGET_PORTS)
    return "egrep '^ *({}) ' || true".format(ports)


def _switch_mac():
    mac = os.environ.get("OBM_SWITCH_MAC", DEFAULT_SWITCH_MAC)
    octets = re.findall(r"[0-9a-fA-F]{2}", mac)
    pytest_require(len(octets) >= 6, "Invalid switch MAC: {}".format(mac))
    return ":".join(octet.lower() for octet in octets[:6])


def _apply_snappi_api_override(snappi_api):
    api_server = os.environ.get("OBM_SNAPPI_API_SERVER")
    if "OBM_SNAPPI_API_USER" in os.environ:
        snappi_api._username = os.environ["OBM_SNAPPI_API_USER"]
    if "OBM_SNAPPI_API_PASSWORD" in os.environ:
        snappi_api._password = os.environ["OBM_SNAPPI_API_PASSWORD"]
    if not api_server:
        return

    host, _, port = api_server.partition(":")
    port = port or "443"
    snappi_api._address = host
    snappi_api._port = port
    logger.info("Using Snappi API override %s:%s", host, port)


def _selected_ports(get_snappi_ports):
    ports_by_name = {
        port["peer_port"]: port
        for port in get_snappi_ports
        if port["peer_device"] == TARGET_DUT and port["peer_port"] in TARGET_PORTS
    }
    missing_ports = [port for port in TARGET_PORTS if port not in ports_by_name]
    pytest_require(
        not missing_ports,
        "Missing requested Snappi links for {}: {}".format(TARGET_DUT, missing_ports),
    )
    return [ports_by_name[port] for port in TARGET_PORTS]


def _ip_subnet(ip_addr, prefix_len):
    return str(ip_interface("{}/{}".format(ip_addr, prefix_len)).network)


def _vlan_memberships(duthost, port):
    result = duthost.shell(
        "sonic-db-cli CONFIG_DB keys 'VLAN_MEMBER|*|{port}'".format(port=port),
        module_ignore_errors=True,
    )
    memberships = []
    for key in result.get("stdout_lines", []):
        fields = key.split("|")
        if len(fields) != 3:
            continue
        vlan = fields[1].replace("Vlan", "")
        entry = duthost.shell(
            "sonic-db-cli CONFIG_DB hget 'VLAN_MEMBER|Vlan{vlan}|{port}' tagging_mode".format(
                vlan=vlan,
                port=port,
            ),
            module_ignore_errors=True,
        )
        tagging_mode = entry.get("stdout", "").strip() or "tagged"
        memberships.append((vlan, tagging_mode))
    return memberships


def _build_testbed_config(snappi_api, selected_ports, switch_mac):
    testbed_config = snappi_api.config()
    selected_ports = [
        dict(list(port.items()) + [("port_id", port_id)])
        for port_id, port in enumerate(selected_ports)
    ]

    pytest_assert(len(set(port["speed"] for port in selected_ports)) == 1, "Ports have different link speeds")
    for port in selected_ports:
        testbed_config.ports.port(name="Port {}".format(port["port_id"]), location=port["location"])

    speed_gbps = int(int(selected_ports[0]["speed"]) / 1000)
    testbed_config.options.port_options.location_preemption = False
    layer1 = testbed_config.layer1.layer1()[-1]
    layer1.name = "L1 config"
    layer1.port_names = [port.name for port in testbed_config.ports]
    layer1.speed = "speed_{}_gbps".format(speed_gbps)
    layer1.ieee_media_defaults = False
    layer1.auto_negotiate = False
    layer1.auto_negotiation.link_training = True
    layer1.auto_negotiation.rs_fec = True

    port_config_list = []
    for port in selected_ports:
        port_id = port["port_id"]
        tgen_ip = "198.18.{}.2".format(port_id)
        dut_ip = "198.18.{}.1".format(port_id)
        tgen_mac = "00:{:02d}:22:33:44:01".format(port_id)
        port_config_list.append(
            SnappiPortConfig(
                id=port_id,
                ip=tgen_ip,
                mac=tgen_mac,
                gw=dut_ip,
                gw_mac=switch_mac,
                prefix_len=24,
                port_type=SnappiPortType.RtrInterface,
                peer_port=port["peer_port"],
            )
        )

    return testbed_config, port_config_list, selected_ports


def _install_static_forwarding(duthost, port_config_list):
    configured = []
    try:
        for port_config in port_config_list:
            dut_ip = "{}/{}".format(port_config.gateway, port_config.prefix_len)
            subnet = _ip_subnet(port_config.ip, port_config.prefix_len)
            vlan_memberships = _vlan_memberships(duthost, port_config.peer_port)
            for vlan, _ in vlan_memberships:
                duthost.shell(
                    "sudo config vlan member del {vlan} {dev}".format(
                        vlan=vlan,
                        dev=port_config.peer_port,
                    )
                )
            duthost.shell(
                "sudo config interface startup {dev}; "
                "sudo config interface ip add {dev} {dut_ip}".format(
                    dev=port_config.peer_port,
                    dut_ip=dut_ip,
                )
            )
            duthost.shell(
                "sudo ip neigh replace {ip} lladdr {mac} dev {dev} nud permanent".format(
                    ip=port_config.ip,
                    mac=port_config.mac,
                    dev=port_config.peer_port,
                )
            )
            duthost.shell(
                "sudo ip route replace {subnet} dev {dev} proto static scope link".format(
                    subnet=subnet,
                    dev=port_config.peer_port,
                )
            )
            logger.info(
                "Installed static forwarding for %s: subnet=%s tgen_ip=%s tgen_mac=%s",
                port_config.peer_port,
                subnet,
                port_config.ip,
                port_config.mac,
            )
            configured.append((subnet, dut_ip, port_config.ip, port_config.peer_port, vlan_memberships))
    except Exception:
        _remove_static_forwarding(duthost, configured)
        raise
    time.sleep(5)
    for port_config in port_config_list:
        memberships = _vlan_memberships(duthost, port_config.peer_port)
        pytest_assert(
            not memberships,
            "{} is still a VLAN member after routed setup: {}".format(port_config.peer_port, memberships),
        )
        route = duthost.shell(
            "ip route get {ip}".format(ip=port_config.ip),
            module_ignore_errors=True,
        )
        logger.info("Route lookup for %s: %s", port_config.ip, route.get("stdout", ""))
    return configured


def _log_dut_state(duthost, label):
    vlan_checks = []
    for port in TARGET_PORTS:
        vlan_checks.append(
            "printf '{port}='; sonic-db-cli CONFIG_DB keys 'VLAN_MEMBER|*|{port}' | paste -sd, -".format(
                port=port,
            )
        )
    result = duthost.shell(
        "echo '--- {label}: VLAN memberships ---'; {vlan_checks}; "
        "echo '--- {label}: routes ---'; ip route show | egrep '198\\.18|Vlan1000' || true; "
        "echo '--- {label}: counters ---'; show interfaces counters -a | {counter_filter}".format(
            label=label,
            vlan_checks="; ".join(vlan_checks),
            counter_filter=_target_counter_filter(),
        ),
        module_ignore_errors=True,
    )
    logger.info("DUT state %s:\n%s", label, result.get("stdout", ""))
    return result


def _remove_static_forwarding(duthost, configured_routes):
    for subnet, dut_ip, ip_addr, peer_port, vlan_memberships in reversed(configured_routes):
        duthost.shell(
            "sudo ip route del {subnet} dev {dev} proto static scope link || true; "
            "sudo ip neigh del {ip} dev {dev} || true; "
            "sudo config interface ip remove {dev} {dut_ip} || true".format(
                subnet=subnet,
                ip=ip_addr,
                dev=peer_port,
                dut_ip=dut_ip,
            ),
            module_ignore_errors=True,
        )
        for vlan, tagging_mode in vlan_memberships:
            tagging_arg = "-u " if tagging_mode == "untagged" else ""
            duthost.shell(
                "sudo config vlan member add {tagging_arg}{vlan} {dev} || true".format(
                    tagging_arg=tagging_arg,
                    vlan=vlan,
                    dev=peer_port,
                ),
                module_ignore_errors=True,
            )


def _add_full_mesh_ipv4_flows(testbed_config, port_config_list, rate_percent, frame_size, duration_sec, switch_mac):
    per_flow_rate = rate_percent / float(len(port_config_list) - 1)
    for tx_port_config in port_config_list:
        for rx_port_config in port_config_list:
            if tx_port_config.id == rx_port_config.id:
                continue

            flow = testbed_config.flows.flow(
                name="{} to {}".format(tx_port_config.peer_port, rx_port_config.peer_port)
            )[-1]
            flow.tx_rx.port.tx_name = testbed_config.ports[tx_port_config.id].name
            flow.tx_rx.port.rx_name = testbed_config.ports[rx_port_config.id].name

            eth, ipv4 = flow.packet.ethernet().ipv4()
            eth.src.value = tx_port_config.mac
            eth.dst.value = switch_mac
            ipv4.src.value = tx_port_config.ip
            ipv4.dst.value = rx_port_config.ip
            ipv4.priority.choice = ipv4.priority.DSCP
            ipv4.priority.dscp.phb.values = [0]

            flow.size.fixed = frame_size
            flow.rate.percentage = per_flow_rate
            flow.duration.fixed_seconds.seconds = duration_sec
            flow.metrics.enable = True
            flow.metrics.loss = True


def _start_traffic(snappi_api):
    control_state = snappi_api.control_state()
    control_state.traffic.flow_transmit.state = control_state.traffic.flow_transmit.START
    snappi_api.set_control_state(control_state)


def _stop_traffic(snappi_api):
    control_state = snappi_api.control_state()
    control_state.traffic.flow_transmit.state = control_state.traffic.flow_transmit.STOP
    snappi_api.set_control_state(control_state)


def _wait_for_flows_to_stop(snappi_api, flow_names, timeout_sec):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        request = snappi_api.metrics_request()
        request.flow.flow_names = flow_names
        rows = snappi_api.get_metrics(request).flow_metrics
        transmit_states = [row.transmit for row in rows]
        if len(rows) == len(flow_names) and set(transmit_states) == {"stopped"}:
            return rows
        time.sleep(1)
    logger.warning("Flows did not report stopped within %s seconds", timeout_sec)
    return _get_flow_metrics(snappi_api, flow_names)


def _get_flow_metrics(snappi_api, flow_names):
    request = snappi_api.metrics_request()
    request.flow.flow_names = flow_names
    return snappi_api.get_metrics(request).flow_metrics


def _get_port_metrics(snappi_api, port_names):
    request = snappi_api.metrics_request()
    request.port.port_names = port_names
    return snappi_api.get_metrics(request).port_metrics


def _run_obm_soc(duthost, local_script):
    remote_script = "/tmp/th5p512_obm.soc"
    syncd_script = "/th5p512_obm.soc"
    syncd_log = "/th5p512_obm_dump.log"

    pytest_require(os.path.exists(local_script), "OBM SOC script not found: {}".format(local_script))
    duthost.copy(src=local_script, dest=remote_script)
    duthost.shell("docker cp {} syncd:{}".format(remote_script, syncd_script))
    result = duthost.shell(
        "docker exec syncd sh -lc \"rm -f {0}; bcmcmd 'rcload {1}'; cat {0}\"".format(
            syncd_log,
            syncd_script,
        ),
        module_ignore_errors=True,
    )
    logger.info("OBM SOC stdout:\n%s", result.get("stdout", ""))
    logger.info("OBM SOC stderr:\n%s", result.get("stderr", ""))
    pytest_assert(result["rc"] == 0, "OBM SOC script failed: {}".format(result))

    return result["stdout"]


def test_7060x6_full_mesh_ipv4_with_obm_capture(
    duthosts,
    get_snappi_ports,  # noqa: F811
    snappi_api,  # noqa: F811
):
    """Send 100G line-rate full-mesh IPv4 traffic on eight 7060X6 ports while collecting OBM counters."""
    duration_sec = _int_env("OBM_EXPERIMENT_DURATION_SEC", 60)
    frame_size = _int_env("OBM_EXPERIMENT_FRAME_SIZE", 1024)
    line_rate_percent = _float_env("OBM_EXPERIMENT_RATE_PERCENT", 100.0)
    min_port_rx_ratio = _float_env("OBM_MIN_PORT_RX_RATIO", 0.50)
    soc_script = os.environ.get("OBM_SOC_SCRIPT", "/tmp/th5p512_obm.soc")
    switch_mac = _switch_mac()

    _apply_snappi_api_override(snappi_api)
    selected_ports = _normalize_selected_port_locations(_selected_ports(get_snappi_ports))
    logger.info("Selected DUT/TGEN ports: %s", [(p["peer_port"], p["location"]) for p in selected_ports])

    testbed_config = None
    port_config_list = []
    configured_routes = []
    try:
        testbed_config, port_config_list, selected_ports = _build_testbed_config(
            snappi_api, selected_ports, switch_mac
        )
        _bypass_resource_group_conversion(snappi_api, testbed_config)
        pytest_require(len(port_config_list) == len(TARGET_PORTS), "Failed to configure all target ports")

        _add_full_mesh_ipv4_flows(
            testbed_config,
            port_config_list,
            line_rate_percent,
            frame_size,
            duration_sec,
            switch_mac,
        )
        flow_names = [flow.name for flow in testbed_config.flows]
        snappi_api.set_config(testbed_config)

        duthost = duthosts[TARGET_DUT]
        configured_routes = _install_static_forwarding(duthost, port_config_list)
        duthost.command("sudo sonic-clear counters")
        _log_dut_state(duthost, "before traffic")

        start_time = time.time()
        _start_traffic(snappi_api)
        time.sleep(min(5, duration_sec))
        _log_dut_state(duthost, "during traffic")
        obm_output = _run_obm_soc(duthost, soc_script)
        time.sleep(max(0, duration_sec - (time.time() - start_time)))
        _stop_traffic(snappi_api)
        flow_rows = _wait_for_flows_to_stop(snappi_api, flow_names, timeout_sec=30)
        if not flow_rows:
            flow_rows = _get_flow_metrics(snappi_api, flow_names)
        port_rows = _get_port_metrics(snappi_api, [port.name for port in testbed_config.ports])
        _log_dut_state(duthost, "after traffic")

        failures = []
        for row in flow_rows:
            logger.info(
                "Flow %s: tx=%s rx=%s loss=%s transmit=%s",
                row.name,
                row.frames_tx,
                row.frames_rx,
                getattr(row, "loss", None),
                row.transmit,
            )
            if row.frames_tx <= 0:
                failures.append("No transmitted frames for {}".format(row.name))

        for row in port_rows:
            logger.info(
                "Port %s: tx=%s rx=%s tx_rate=%s rx_rate=%s link=%s",
                row.name,
                row.frames_tx,
                row.frames_rx,
                getattr(row, "frames_tx_rate", None),
                getattr(row, "frames_rx_rate", None),
                getattr(row, "link", None),
            )
            if row.frames_tx <= 0:
                failures.append("No transmitted port frames for {}".format(row.name))
            min_rx = row.frames_tx * min_port_rx_ratio
            if row.frames_rx < min_rx:
                failures.append(
                    "Received port frames too low for {}: rx={} tx={} min_ratio={}".format(
                        row.name,
                        row.frames_rx,
                        row.frames_tx,
                        min_port_rx_ratio,
                    )
                )

        pytest_assert(not failures, "; ".join(failures))

        pytest_assert("finished" in obm_output, "OBM SOC log did not include completion marker")
    finally:
        try:
            _stop_traffic(snappi_api)
        except Exception as exc:
            logger.warning("Failed to stop Snappi traffic during cleanup: %s", exc)
        if configured_routes:
            _remove_static_forwarding(duthosts[TARGET_DUT], configured_routes)
