# DualToR Nightly Test Plan

## Overview

This document defines the required test features and test scripts for the SONiC DualToR nightly test suite. It also includes a cross-platform diff analysis comparing what each active nightly schedule runs versus the baseline to identify coverage gaps.

> **Note:** This analysis is based on the Arista 7050CX3 DualToR + T0 nightly test run as the baseline.

## Scope

|HWSKU|Vendor|Topology|
|---|---|---|
|Arista-7050CX3-32C-C32|Arista|dualtor/dualtor-aa|
|Arista-7050CX3-32S-C32|Arista|dualtor/dualtor-aa|
|Arista-7260CX3-D108C8|Arista|dualtor-120|
|Arista-7260CX3-C64|Arista|dualtor-aa-56|
|Cisco-8101C01-V64|Cisco|dualtor-aa-64-breakout|
|Cisco-8101C01-C32|Cisco|dualtor/dualtor-aa|


## Required Test Features

The following feature areas are required to run in the DualToR nightly. They map to test directories under `tests/` in the sonic-mgmt repository.

### Globally Excluded Features (all schedules)

These features are excluded across **all** active DualToR nightly schedules:

`acstests`, `console`, `dash`, `ixai`, `k8s`, `macsec`, `mclag`, `mpls`, `mx`, `pfc_asym`, `ptftests`, `sai_qualify`, `saitests`, `scripts`, `snappi_tests`, `span`, `sub_port_interfaces`, `voq`, `wan`, `wan_test`

### Feature Coverage


94 feature areas, 456 test scripts total.

| Scripts | Feature | Test Scripts |
|---|---|---|
| 6 | `acl` | `acl/custom_acl_table/test_custom_acl_table.py`<br>`acl/null_route/test_null_route_helper.py`<br>`acl/test_acl.py`<br>`acl/test_acl_outer_vlan.py`<br>`acl/test_src_mac_rewrite.py`<br>`acl/test_stress_acl.py` |
| 5 | `acms` | `acms/test_acms_bootstrap.py`<br>`acms/test_acms_bootstrap_monitor.py`<br>`acms/test_acms_cert_converter.py`<br>`acms/test_acms_cert_downloader.py`<br>`acms/test_acms_start.py` |
| 9 | `arp` | `arp/test_arp_dualtor.py`<br>`arp/test_arp_extended.py`<br>`arp/test_arp_update.py`<br>`arp/test_arpall.py`<br>`arp/test_neighbor_mac.py`<br>`arp/test_neighbor_mac_noptf.py`<br>`arp/test_stress_arp.py`<br>`arp/test_tagged_arp.py`<br>`arp/test_unknown_mac.py` |
| 1 | `auditd` | `auditd/test_auditd.py` |
| 1 | `autorestart` | `autorestart/test_container_autorestart.py` |
| 3 | `bfd` | `bfd/test_bfd.py`<br>`bfd/test_bfd_static_route.py`<br>`bfd/test_bfd_traffic.py` |
| 48 | `bgp` | `bgp/reliable_tsa/test_reliable_tsa_flaky.py`<br>`bgp/reliable_tsa/test_reliable_tsa_stable.py`<br>`bgp/test_4-byte_asn_community.py`<br>`bgp/test_bgp_4-byte_as_trans.py`<br>`bgp/test_bgp_allow_list.py`<br>`bgp/test_bgp_allow_list_m0_olt.py`<br>`bgp/test_bgp_aspath_prepend_internal_only.py`<br>`bgp/test_bgp_authentication.py`<br>`bgp/test_bgp_azng_migration.py`<br>`bgp/test_bgp_bbr.py`<br>`bgp/test_bgp_bbr_default_state.py`<br>`bgp/test_bgp_bounce.py`<br>`bgp/test_bgp_command.py`<br>`bgp/test_bgp_dual_asn.py`<br>`bgp/test_bgp_establish_combo.py`<br>`bgp/test_bgp_fact.py`<br>`bgp/test_bgp_gr_helper.py`<br>`bgp/test_bgp_multipath_relax.py`<br>`bgp/test_bgp_peer_shutdown.py`<br>`bgp/test_bgp_port_disable.py`<br>`bgp/test_bgp_queue.py`<br>`bgp/test_bgp_route_neigh_learning.py`<br>`bgp/test_bgp_router_id.py`<br>`bgp/test_bgp_sentinel.py`<br>`bgp/test_bgp_session.py`<br>`bgp/test_bgp_session_flap.py`<br>`bgp/test_bgp_speaker.py`<br>`bgp/test_bgp_stress_link_flap.py`<br>`bgp/test_bgp_suppress_fib.py`<br>`bgp/test_bgp_update_replication.py`<br>`bgp/test_bgp_update_timer.py`<br>`bgp/test_bgp_vnet.py`<br>`bgp/test_bgpmon.py`<br>`bgp/test_bgpmon_v6.py`<br>`bgp/test_fairwater_bgp_multipath_relax.py`<br>`bgp/test_frr_config_check.py`<br>`bgp/test_ipv6_bgp_scale.py`<br>`bgp/test_ipv6_nlri_over_ipv4.py`<br>`bgp/test_passive_peering.py`<br>`bgp/test_ping_bgp_neighbor.py`<br>`bgp/test_prefix_list.py`<br>`bgp/test_prefix_list_internal_only.py`<br>`bgp/test_seq_idf_isolation.py`<br>`bgp/test_startup_tsa_tsb_service.py`<br>`bgp/test_traffic_shift.py`<br>`bgp/test_traffic_shift_lc.py`<br>`bgp/test_traffic_shift_sup.py` |
| 5 | `bmp` | `bmp/test_bmp_configdb.py`<br>`bmp/test_bmp_redis_instance.py`<br>`bmp/test_bmp_statedb.py`<br>`bmp/test_docker_restart.py`<br>`bmp/test_frr_bmp_sanity.py` |
| 3 | `cacl` | `cacl/test_cacl_application.py`<br>`cacl/test_cacl_function.py`<br>`cacl/test_ebtables_application.py` |
| 1 | `clock` | `clock/test_clock.py` |
| 1 | `configlet` | `configlet/test_add_rack.py` |
| 2 | `consecutive-actions` | `consecutive-actions/test_config_reload.py`<br>`consecutive-actions/test_load_minigraph.py` |
| 1 | `container_checker` | `container_checker/test_container_checker.py` |
| 1 | `container_hardening` | `container_hardening/test_container_hardening.py` |
| 1 | `container_upgrade` | `container_upgrade/test_container_upgrade.py` |
| 1 | `copp` | `copp/test_copp.py` |
| 1 | `counter` | `counter/test_xon_xoff.py` |
| 1 | `cpu_shaper` | `cpu_shaper/test_cpu_shaper.py` |
| 2 | `crm` | `crm/test_crm.py`<br>`crm/test_crm_available.py` |
| 2 | `database` | `database/test_db_config.py`<br>`database/test_db_scripts.py` |
| 1 | `db_migrator` | `db_migrator/test_migrate_dns.py` |
| 2 | `decap` | `decap/test_decap.py`<br>`decap/test_subnet_decap.py` |
| 6 | `dhcp_relay` | `dhcp_relay/test_dhcp_counter_stress.py`<br>`dhcp_relay/test_dhcp_pkt_fwd.py`<br>`dhcp_relay/test_dhcp_pkt_recv.py`<br>`dhcp_relay/test_dhcp_relay.py`<br>`dhcp_relay/test_dhcp_relay_stress.py`<br>`dhcp_relay/test_dhcpv6_relay.py` |
| 3 | `dhcp_server` | `dhcp_server/test_dhcp_server.py`<br>`dhcp_server/test_dhcp_server_multi_vlans.py`<br>`dhcp_server/test_dhcp_server_stress.py` |
| 1 | `disk` | `disk/test_disk_exhaustion.py` |
| 3 | `dns` | `dns/static_dns/test_static_dns.py`<br>`dns/test_dns_resolv.py`<br>`dns/test_dns_resolv_conf.py` |
| 2 | `drop_packets` | `drop_packets/test_configurable_drop_counters.py`<br>`drop_packets/test_drop_counters.py` |
| 14 | `dualtor` | `dualtor/test_bgp_block_loopback1.py`<br>`dualtor/test_ipinip.py`<br>`dualtor/test_mux_port_iptables_entries.py`<br>`dualtor/test_orch_stress.py`<br>`dualtor/test_orchagent_active_tor_downstream.py`<br>`dualtor/test_orchagent_mac_move.py`<br>`dualtor/test_orchagent_slb.py`<br>`dualtor/test_orchagent_standby_tor_downstream.py`<br>`dualtor/test_standalone_tunnel_route.py`<br>`dualtor/test_standby_tor_upstream_mux_toggle.py`<br>`dualtor/test_switchover_failure.py`<br>`dualtor/test_switchover_faulty_ycable.py`<br>`dualtor/test_tor_ecn.py`<br>`dualtor/test_tunnel_memory_leak.py` |
| 8 | `dualtor_io` | `dualtor_io/test_grpc_server_failure.py`<br>`dualtor_io/test_heartbeat_failure.py`<br>`dualtor_io/test_link_drop.py`<br>`dualtor_io/test_link_failure.py`<br>`dualtor_io/test_normal_op.py`<br>`dualtor_io/test_switchover_impact.py`<br>`dualtor_io/test_tor_bgp_failure.py`<br>`dualtor_io/test_tor_failure.py` |
| 7 | `dualtor_mgmt` | `dualtor_mgmt/test_dualtor_bgp_update_delay.py`<br>`dualtor_mgmt/test_dualtor_setup_mux_ports.py`<br>`dualtor_mgmt/test_egress_drop_nvidia.py`<br>`dualtor_mgmt/test_grpc_periodical_sync.py`<br>`dualtor_mgmt/test_ingress_drop.py`<br>`dualtor_mgmt/test_server_failure.py`<br>`dualtor_mgmt/test_toggle_mux.py` |
| 8 | `dut_console` | `dut_console/test_console_baud_rate.py`<br>`dut_console/test_console_chassis_conn.py`<br>`dut_console/test_escape_character.py`<br>`dut_console/test_escape_character.py`<br>`dut_console/test_idle_timeout.py`<br>`dut_console/test_idle_timeout.py`<br>`dut_console/test_non_ascii_output.py`<br>`dut_console/test_non_ascii_output.py` |
| 8 | `ecmp` | `ecmp/inner_hashing/test_fgnhg_inner_hashing_internal.py`<br>`ecmp/inner_hashing/test_inner_hashing.py`<br>`ecmp/inner_hashing/test_inner_hashing_lag.py`<br>`ecmp/inner_hashing/test_wr_inner_hashing.py`<br>`ecmp/inner_hashing/test_wr_inner_hashing_lag.py`<br>`ecmp/test_ecmp_balance.py`<br>`ecmp/test_ecmp_sai_value.py`<br>`ecmp/test_fgnhg.py` |
| 3 | `everflow` | `everflow/test_everflow_ipv6.py`<br>`everflow/test_everflow_per_interface.py`<br>`everflow/test_everflow_testbed.py` |
| 5 | `fdb` | `fdb/test_fdb.py`<br>`fdb/test_fdb_flush.py`<br>`fdb/test_fdb_mac_expire.py`<br>`fdb/test_fdb_mac_learning.py`<br>`fdb/test_fdb_mac_move.py` |
| 1 | `fib` | `fib/test_fib.py` |
| 2 | `filterleaf` | `filterleaf/test_filterleaf_subinterface.py`<br>`filterleaf/test_filterleaf_with_routemap.py` |
| 1 | `fips` | `fips/test_fips.py` |
| 30 | `generic_config_updater` | `generic_config_updater/test_aaa.py`<br>`generic_config_updater/test_bgp_prefix.py`<br>`generic_config_updater/test_bgp_sentinel.py`<br>`generic_config_updater/test_bgp_speaker.py`<br>`generic_config_updater/test_bgpl.py`<br>`generic_config_updater/test_cacl.py`<br>`generic_config_updater/test_dhcp_relay.py`<br>`generic_config_updater/test_dynamic_acl.py`<br>`generic_config_updater/test_ecn_config_update.py`<br>`generic_config_updater/test_eth_interface.py`<br>`generic_config_updater/test_incremental_qos.py`<br>`generic_config_updater/test_ip_bgp.py`<br>`generic_config_updater/test_kubernetes_config.py`<br>`generic_config_updater/test_lo_interface.py`<br>`generic_config_updater/test_mgmt_interface.py`<br>`generic_config_updater/test_mmu_dynamic_threshold_config_update.py`<br>`generic_config_updater/test_monitor_config.py`<br>`generic_config_updater/test_multiasic_addcluster.py`<br>`generic_config_updater/test_multiasic_idf.py`<br>`generic_config_updater/test_multiasic_linkcrc.py`<br>`generic_config_updater/test_ntp.py`<br>`generic_config_updater/test_packet_trimming_config_asymmetric.py`<br>`generic_config_updater/test_packet_trimming_config_symmetric.py`<br>`generic_config_updater/test_pfcwd_interval.py`<br>`generic_config_updater/test_pfcwd_status.py`<br>`generic_config_updater/test_pg_headroom_update.py`<br>`generic_config_updater/test_portchannel_interface.py`<br>`generic_config_updater/test_static_route.py`<br>`generic_config_updater/test_syslog.py`<br>`generic_config_updater/test_vlan_interface.py` |
| 13 | `gnmi` | `gnmi/test_gnmi.py`<br>`gnmi/test_gnmi_appldb.py`<br>`gnmi/test_gnmi_configdb.py`<br>`gnmi/test_gnmi_countersdb.py`<br>`gnmi/test_gnmi_smartswitch.py`<br>`gnmi/test_gnmi_stress.py`<br>`gnmi/test_gnmic.py`<br>`gnmi/test_gnoi_file.py`<br>`gnmi/test_gnoi_killprocess.py`<br>`gnmi/test_gnoi_os.py`<br>`gnmi/test_gnoi_system.py`<br>`gnmi/test_gnoi_system_reboot.py`<br>`gnmi/test_mimic_hwproxy_cert_rotation.py` |
| 2 | `gnmi_e2e` | `gnmi_e2e/test_gnmi_auth.py`<br>`gnmi_e2e/test_telemetry_auth.py` |
| 2 | `golden_config_infra` | `golden_config_infra/test_config_reload_with_rendered_golden_config.py`<br>`golden_config_infra/test_multiasic_golden_config_verification.py` |
| 2 | `ha` | `ha/test_ha_planned_shutdown.py`<br>`ha/test_ha_steady_state_pl.py` |
| 1 | `hash` | `hash/test_generic_hash.py` |
| 1 | `high_frequency_telemetry` | `high_frequency_telemetry/test_high_frequency_telemetry.py` |
| 1 | `http` | `http/test_http_copy.py` |
| 1 | `iface_loopback_action` | `iface_loopback_action/test_iface_loopback_action.py` |
| 1 | `iface_namingmode` | `iface_namingmode/test_iface_namingmode.py` |
| 2 | `ip` | `ip/link_local/test_link_local_ip.py`<br>`ip/test_ip_packet.py` |
| 4 | `ipfwd` | `ipfwd/test_dip_sip.py`<br>`ipfwd/test_dir_bcast.py`<br>`ipfwd/test_mtu.py`<br>`ipfwd/test_nhop_group.py` |
| 14 | `ixia` | `ixia/ecn/test_dequeue_ecn.py`<br>`ixia/ecn/test_red_accuracy.py`<br>`ixia/ixanvl/test_bgp_conformance.py`<br>`ixia/pfc/test_global_pause.py`<br>`ixia/pfc/test_pfc_congestion.py`<br>`ixia/pfc/test_pfc_pause_lossless.py`<br>`ixia/pfc/test_pfc_pause_lossy.py`<br>`ixia/pfcwd/test_pfcwd_a2a.py`<br>`ixia/pfcwd/test_pfcwd_basic.py`<br>`ixia/pfcwd/test_pfcwd_burst_storm.py`<br>`ixia/pfcwd/test_pfcwd_m2o.py`<br>`ixia/pfcwd/test_pfcwd_runtime_traffic.py`<br>`ixia/test_ixia_traffic.py`<br>`ixia/test_tgen.py` |
| 2 | `kubesonic` | `kubesonic/test_k8s_cleanup.py`<br>`kubesonic/test_k8s_join_disjoin.py` |
| 1 | `l2` | `l2/test_l2_configure.py` |
| 2 | `layer1` | `layer1/test_fec_error.py`<br>`layer1/test_port_error.py` |
| 2 | `lldp` | `lldp/test_lldp.py`<br>`lldp/test_lldp_syncd.py` |
| 1 | `log_fidelity` | `log_fidelity/test_bgp_shutdown.py` |
| 1 | `memory_checker` | `memory_checker/test_memory_checker.py` |
| 1 | `minigraph` | `minigraph/test_masked_services.py` |
| 1 | `monit` | `monit/test_monit_status.py` |
| 2 | `ospf` | `ospf/test_ospf.py`<br>`ospf/test_ospf_bfd.py` |
| 2 | `override_config_table` | `override_config_table/test_override_config_table.py`<br>`override_config_table/test_override_config_table_masic.py` |
| 2 | `packet_trimming` | `packet_trimming/test_packet_trimming_asymmetric.py`<br>`packet_trimming/test_packet_trimming_symmetric.py` |
| 1 | `passw_hardening` | `passw_hardening/test_passw_hardening.py` |
| 7 | `pc` | `pc/test_lag_2.py`<br>`pc/test_lag_member.py`<br>`pc/test_lag_member_forwarding.py`<br>`pc/test_po_cleanup.py`<br>`pc/test_po_update.py`<br>`pc/test_po_voq.py`<br>`pc/test_retry_count.py` |
| 1 | `performance_meter` | `performance_meter/test_performance.py` |
| 7 | `pfcwd` | `pfcwd/test_pfc_config.py`<br>`pfcwd/test_pfcwd_all_port_storm.py`<br>`pfcwd/test_pfcwd_cli.py`<br>`pfcwd/test_pfcwd_function.py`<br>`pfcwd/test_pfcwd_timer_accuracy.py`<br>`pfcwd/test_pfcwd_warm_reboot.py`<br>`pfcwd/test_xon_not_counted.py` |
| 58 | `platform_tests` | `platform_tests/api/test_chassis.py`<br>`platform_tests/api/test_chassis_fans.py`<br>`platform_tests/api/test_component.py`<br>`platform_tests/api/test_fan_drawer.py`<br>`platform_tests/api/test_fan_drawer_fans.py`<br>`platform_tests/api/test_liquid_cooling_leakage.py`<br>`platform_tests/api/test_module.py`<br>`platform_tests/api/test_psu.py`<br>`platform_tests/api/test_psu_fans.py`<br>`platform_tests/api/test_sfp.py`<br>`platform_tests/api/test_thermal.py`<br>`platform_tests/api/test_watchdog.py`<br>`platform_tests/broadcom/test_ser.py`<br>`platform_tests/cli/test_show_chassis_module.py`<br>`platform_tests/cli/test_show_platform.py`<br>`platform_tests/counterpoll/test_counterpoll_watermark.py`<br>`platform_tests/daemon/test_chassisd.py`<br>`platform_tests/daemon/test_fancontrol.py`<br>`platform_tests/daemon/test_ledd.py`<br>`platform_tests/daemon/test_pcied.py`<br>`platform_tests/daemon/test_psud.py`<br>`platform_tests/daemon/test_sensord.py`<br>`platform_tests/daemon/test_syseepromd.py`<br>`platform_tests/fwutil/test_fwutil.py`<br>`platform_tests/link_flap/test_link_flap.py`<br>`platform_tests/mellanox/test_check_sfp_eeprom.py`<br>`platform_tests/mellanox/test_check_sfp_using_ethtool.py`<br>`platform_tests/mellanox/test_check_sysfs.py`<br>`platform_tests/mellanox/test_hw_management_service.py`<br>`platform_tests/mellanox/test_psu_power_threshold.py`<br>`platform_tests/mellanox/test_reboot_cause.py`<br>`platform_tests/sfp/test_sfpshow.py`<br>`platform_tests/sfp/test_sfputil.py`<br>`platform_tests/sfp/test_show_intf_xcvr.py`<br>`platform_tests/test_chassis_reboot.py`<br>`platform_tests/test_cpu_memory_usage.py`<br>`platform_tests/test_first_time_boot_password_change/test_first_time_boot_password_change.py`<br>`platform_tests/test_idle_driver.py`<br>`platform_tests/test_intf_fec.py`<br>`platform_tests/test_kdump.py`<br>`platform_tests/test_link_down.py`<br>`platform_tests/test_link_down_sup.py`<br>`platform_tests/test_liquid_cooling_leakage_detection.py`<br>`platform_tests/test_memory_exhaustion.py`<br>`platform_tests/test_platform_info.py`<br>`platform_tests/test_port_toggle.py`<br>`platform_tests/test_power_budget_info.py`<br>`platform_tests/test_power_off_reboot.py`<br>`platform_tests/test_process_reboot_cause.py`<br>`platform_tests/test_reboot.py`<br>`platform_tests/test_reboot.py`<br>`platform_tests/test_reload_config.py`<br>`platform_tests/test_secure_upgrade.py`<br>`platform_tests/test_sensors.py`<br>`platform_tests/test_sequential_restart.py`<br>`platform_tests/test_thermal_state_db.py`<br>`platform_tests/test_var_log_tmpfs.py`<br>`platform_tests/test_xcvr_info_in_db.py` |
| 1 | `portstat` | `portstat/test_portstat.py` |
| 1 | `process_monitoring` | `process_monitoring/test_critical_process_monitoring.py` |
| 11 | `qos` | `qos/test_buffer.py`<br>`qos/test_buffer_traditional.py`<br>`qos/test_ecn_config.py`<br>`qos/test_oq_watchdog.py`<br>`qos/test_pfc_counters.py`<br>`qos/test_pfc_pause.py`<br>`qos/test_qos_dscp_mapping.py`<br>`qos/test_qos_masic.py`<br>`qos/test_qos_sai.py`<br>`qos/test_tunnel_qos_remap.py`<br>`qos/test_voq_watchdog.py` |
| 3 | `radv` | `radv/test_radv_ipv6_ra.py`<br>`radv/test_radv_restart.py`<br>`radv/test_radv_run.py` |
| 1 | `read_mac` | `read_mac/test_read_mac_metadata.py` |
| 1 | `reset_factory` | `reset_factory/test_reset_factory.py` |
| 3 | `restapi` | `restapi/test_restapi.py`<br>`restapi/test_restapi_client_cert_auth.py`<br>`restapi/test_restapi_vxlan_ecmp.py` |
| 8 | `root` | `test_features.py`<br>`test_interfaces.py`<br>`test_nbr_health.py`<br>`test_pktgen.py`<br>`test_posttest.py`<br>`test_pretest.py`<br>`test_pretest.py`<br>`test_procdockerstatsd.py` |
| 9 | `route` | `route/test_default_route.py`<br>`route/test_duplicate_route.py`<br>`route/test_forced_mgmt_route.py`<br>`route/test_route_bgp_ecmp.py`<br>`route/test_route_consistency.py`<br>`route/test_route_flap.py`<br>`route/test_route_flow_counter.py`<br>`route/test_route_perf.py`<br>`route/test_static_route.py` |
| 1 | `scp` | `scp/test_scp_copy.py` |
| 2 | `session_monitor` | `session_monitor/test_bgp_session_tracker.py`<br>`session_monitor/test_link_state_tracker.py` |
| 3 | `show_techsupport` | `show_techsupport/test_auto_techsupport.py`<br>`show_techsupport/test_techsupport.py`<br>`show_techsupport/test_techsupport_no_secret.py` |
| 3 | `smartswitch` | `smartswitch/platform_tests/test_dpu_show_platform_temperature.py`<br>`smartswitch/platform_tests/test_platform_dpu.py`<br>`smartswitch/platform_tests/test_reload_dpu.py` |
| 14 | `snmp` | `snmp/test_snmp_cpu.py`<br>`snmp/test_snmp_default_route.py`<br>`snmp/test_snmp_fdb.py`<br>`snmp/test_snmp_interfaces.py`<br>`snmp/test_snmp_link_local.py`<br>`snmp/test_snmp_lldp.py`<br>`snmp/test_snmp_loopback.py`<br>`snmp/test_snmp_memory.py`<br>`snmp/test_snmp_pfc_counters.py`<br>`snmp/test_snmp_phy_entity.py`<br>`snmp/test_snmp_psu.py`<br>`snmp/test_snmp_queue.py`<br>`snmp/test_snmp_queue_counters.py`<br>`snmp/test_snmp_v2mib.py` |
| 4 | `srv6` | `srv6/test_srv6_basic_sanity.py`<br>`srv6/test_srv6_dataplane.py`<br>`srv6/test_srv6_static_config.py`<br>`srv6/test_srv6_vlan_forwarding.py` |
| 4 | `ssh` | `ssh/test_ssh_ciphers.py`<br>`ssh/test_ssh_default_password.py`<br>`ssh/test_ssh_limit.py`<br>`ssh/test_ssh_stress.py` |
| 1 | `stress` | `stress/test_stress_routes.py` |
| 4 | `syslog` | `syslog/test_logrotate.py`<br>`syslog/test_syslog.py`<br>`syslog/test_syslog_rate_limit.py`<br>`syslog/test_syslog_source_ip.py` |
| 3 | `system_health` | `system_health/test_system_health.py`<br>`system_health/test_system_status.py`<br>`system_health/test_watchdog.py` |
| 6 | `tacacs` | `tacacs/test_accounting.py`<br>`tacacs/test_authorization.py`<br>`tacacs/test_command_set.py`<br>`tacacs/test_jit_user.py`<br>`tacacs/test_ro_disk.py`<br>`tacacs/test_rw_user.py` |
| 5 | `telemetry` | `telemetry/test_events.py`<br>`telemetry/test_telemetry.py`<br>`telemetry/test_telemetry_cert_rotation.py`<br>`telemetry/test_telemetry_poll.py`<br>`telemetry/test_telemetry_show_cli.py` |
| 1 | `testbed_setup` | `testbed_setup/test_populate_fdb.py` |
| 2 | `transceiver` | `transceiver/cli/show/test_transceiver_info_cli.py`<br>`transceiver/cmis_cdb_firmware_upgrade/test_firmware_upgrade.py` |
| 4 | `upgrade_path` | `upgrade_path/test_multi_hop_upgrade_path.py`<br>`upgrade_path/test_upgrade_gnoi.py`<br>`upgrade_path/test_upgrade_path.py`<br>`upgrade_path/test_warmboot_data_consistency.py` |
| 6 | `vlan` | `vlan/test_autostate_disabled.py`<br>`vlan/test_host_vlan.py`<br>`vlan/test_secondary_subnet.py`<br>`vlan/test_vlan.py`<br>`vlan/test_vlan_ping.py`<br>`vlan/test_vlan_ports_down.py` |
| 18 | `vxlan` | `vxlan/test_scale_ecmp.py`<br>`vxlan/test_vnet_bgp_route_precedence.py`<br>`vxlan/test_vnet_decap.py`<br>`vxlan/test_vnet_monitor.py`<br>`vxlan/test_vnet_route_leak.py`<br>`vxlan/test_vnet_vxlan.py`<br>`vxlan/test_vxlan_bfd_tsa.py`<br>`vxlan/test_vxlan_crm.py`<br>`vxlan/test_vxlan_decap.py`<br>`vxlan/test_vxlan_ecmp.py`<br>`vxlan/test_vxlan_ecmp_switchover.py`<br>`vxlan/test_vxlan_ecmp_vnet_ping.py`<br>`vxlan/test_vxlan_multi_tunnel.py`<br>`vxlan/test_vxlan_route_advertisement.py`<br>`vxlan/test_vxlan_tunnel_route_scale.py`<br>`vxlan/test_vxlan_underlay_ecmp.py`<br>`vxlan/test_vxlan_vnet_bgp_subintf.py`<br>`vxlan/test_vxlan_vnet_ping_tsa.py` |
| 1 | `wol` | `wol/test_wol.py` |
| 1 | `zmq` | `zmq/test_gnmi_zmq.py` |


## Cross-Platform Diff Analysis

### Platform Coverage Matrix


| Feature | Baseline | 7050cx3 dualtor | 7050cx3 dualtor-aa | 7260cx3 dualtor-120 | 7260cx3 dualtor-aa-56 | 8101c1-c32 dualtor | 8101c1-c32 dualtor-aa |
|---|---|---|---|---|---|---|---|
| `acl` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `acms` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `arp` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `auditd` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `autorestart` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `bfd` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `bgp` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `bmp` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `cacl` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `clock` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `configlet` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `consecutive-actions` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `container_checker` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `container_hardening` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `container_upgrade` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `copp` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `counter` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `cpu_shaper` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `crm` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `database` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `db_migrator` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `decap` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dhcp_relay` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dhcp_server` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `disk` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dns` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `drop_packets` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dualtor` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dualtor_io` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dualtor_mgmt` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dut_console` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ecmp` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `everflow` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `fdb` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `fib` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `filterleaf` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `fips` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `generic_config_updater` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `gnmi` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `gnmi_e2e` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `golden_config_infra` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ha` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `hash` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `high_frequency_telemetry` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `http` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `iface_loopback_action` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `iface_namingmode` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ip` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ipfwd` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `l2` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `layer1` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `lldp` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `log_fidelity` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `memory_checker` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `minigraph` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `monit` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ospf` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `override_config_table` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `packet_trimming` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `passw_hardening` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `pc` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `performance_meter` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `pfcwd` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `platform_tests` | ✅ | ❌⚠️ | ❌⚠️ | ❌⚠️ | ❌⚠️ | ✅ | ✅ |
| `portstat` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `process_monitoring` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `qos` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `radv` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `read_mac` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `reset_factory` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `restapi` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `root` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `route` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `scp` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `session_monitor` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `show_techsupport` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `smartswitch` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌⚠️ | ❌⚠️ |
| `snmp` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `srv6` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌⚠️ | ❌⚠️ |
| `ssh` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `stress` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `syslog` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `system_health` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `tacacs` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `telemetry` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `testbed_setup` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `transceiver` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `upgrade_path` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `vlan` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `vxlan` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `wol` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `zmq` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Legend:** ✅ Included | ❌ Excluded | ❌⚠️ Gap (excluded here, runs on baseline) | ✅🔶 Extra coverage (runs here, excluded on baseline)

### Cisco 8101 DualToR Gap Analysis

This subsection triages the cases that are skipped on the **Cisco 8101 (C32) DualToR** nightly. Two comparisons are used:

- **vs 7050CX3 DualToR** — cases that run on the Arista 7050CX3 *dualtor* nightly but are skipped on 8101 dualtor (surfaces genuine Cisco/Q200 platform behavior).
- **vs 7050CX3 T0** — cases that run on the Arista 7050CX3 *t0* nightly but are skipped on 8101 dualtor.

Each skipped case was classified into one of three buckets:

- 🟢 **Valid skip** – genuine Cisco / Q200 (Cisco-8000) ASIC limitation or a test that is not Cisco-specific skip. Acceptable coverage gap.
- 🔴 **Should be run** – case is skipped today but ought to be covered on 8101; tracked as a real coverage gap.
- 🟠 **Needs double-confirmation** – skip reason is stale or questionable and must be re-validated on current 8101 images.

#### 🟢 Valid skips (genuine platform behavior — acceptable gaps)

| Cases | Comparison | Reason |
| --- | --- | --- |
| `arp.test_unknown_mac.TestUnknownMac.test_unknown_mac[dscp-3]`<br>`arp.test_unknown_mac.TestUnknownMac.test_unknown_mac[dscp-4]`<br>`arp.test_unknown_mac.TestUnknownMac.test_unknown_mac[dscp-8]` | vs 7050CX3 DualToR | Cisco-8000 floods unknown-unicast packets instead of dropping them. |
| `cpu_shaper.test_cpu_shaper.test_cpu_queue_shaper[<DUT>]` | vs 7050CX3 DualToR | Marked `skip('broadcom')` — not applicable to Cisco. |
| `drop_packets.test_drop_counters.test_ip_is_zero_addr[port_channel_members-<DUT>-ipv4-dst]`<br>`drop_packets.test_drop_counters.test_ip_is_zero_addr[port_channel_members-<DUT>-ipv4-src]`<br>`drop_packets.test_drop_counters.test_ip_is_zero_addr[port_channel_members-<DUT>-ipv6-dst]`<br>`drop_packets.test_drop_counters.test_ip_is_zero_addr[port_channel_members-<DUT>-ipv6-src]`<br>`drop_packets.test_drop_counters.test_ip_is_zero_addr[vlan_members-<DUT>-ipv4-dst]`<br>`drop_packets.test_drop_counters.test_ip_is_zero_addr[vlan_members-<DUT>-ipv4-src]`<br>`drop_packets.test_drop_counters.test_ip_is_zero_addr[vlan_members-<DUT>-ipv6-dst]`<br>`drop_packets.test_drop_counters.test_ip_is_zero_addr[vlan_members-<DUT>-ipv6-src]` | vs 7050CX3 DualToR | 8101/Q200 drops packets when destination is `0.0.0.0`. |
| `ecmp.test_ecmp_sai_value.test_ecmp_hash_seed_value[<DUT>-common]`<br>`ecmp.test_ecmp_sai_value.test_ecmp_hash_seed_value[<DUT>-reboot]`<br>`ecmp.test_ecmp_sai_value.test_ecmp_hash_seed_value[<DUT>-reload]`<br>`ecmp.test_ecmp_sai_value.test_ecmp_hash_seed_value[<DUT>-restart_syncd]`<br>`ecmp.test_ecmp_sai_value.test_ecmp_offset_value[<DUT>-common]`<br>`ecmp.test_ecmp_sai_value.test_ecmp_offset_value[<DUT>-reboot]`<br>`ecmp.test_ecmp_sai_value.test_ecmp_offset_value[<DUT>-reload]`<br>`ecmp.test_ecmp_sai_value.test_ecmp_offset_value[<DUT>-restart_syncd]` | vs 7050CX3 DualToR | Relies on Broadcom-shell-specific register reads; will not run on any Cisco platform. |
| `generic_config_updater.test_eth_interface.test_toggle_pfc_asym[None-off]`<br>`generic_config_updater.test_eth_interface.test_toggle_pfc_asym[None-on]` | vs 7050CX3 DualToR | Asymmetric PFC is not supported on Q200. |
| `qos.test_qos_sai.TestQosSai.testQosSaiHeadroomPoolSize[single_asic]`<br>`qos.test_qos_sai.TestQosSai.testQosSaiHeadroomPoolWatermark[single_asic]`<br>`qos.test_qos_sai.TestQosSai.testQosSaiPgHeadroomWatermark[single_asic]` | vs 7050CX3 DualToR | No headroom pool on Q200; alternative covered by `testQosSaiSharedReservationSize`. |
| `platform_tests.api.test_fan_drawer.TestFanDrawerApi.test_get_serial[<DUT>]`<br>`platform_tests.api.test_fan_drawer_fans.TestFanDrawerFans.test_get_serial[<DUT>]`<br>`platform_tests.api.test_fan_drawer_fans.TestFanDrawerFans.test_set_fans_led[<DUT>]`<br>`platform_tests.api.test_psu.TestPsuApi.test_led[<DUT>]`<br>`platform_tests.api.test_psu_fans.TestPsuFans.test_set_fans_led[<DUT>]`<br>`platform_tests.api.test_thermal.TestThermalApi.test_get_model[<DUT>]`<br>`platform_tests.api.test_thermal.TestThermalApi.test_get_serial[<DUT>]`<br>`platform_tests.broadcom.test_ser.test_ser[None]`<br>`platform_tests.dmemos.test_sensord.test_pmon_sensord_sighup`<br>`platform_tests.dmemos.test_sensord.test_pmon_sensord_sigkill`<br>`platform_tests.dmemos.test_sensord.test_pmon_sensord_sigterm`<br>`platform_tests.test_platform_info.test_thermal_control_load_invalid_format_json[<DUT>]`<br>`platform_tests.test_platform_info.test_thermal_control_load_invalid_value_json[<DUT>]`<br>`platform_tests.test_reload_config.test_reload_configuration_checks[<DUT>]`<br>`platform_tests.test_var_log_tmpfs.test_var_log_tmpfs[<DUT>]` | vs 7050CX3 T0 | Hardware-specific (LED/PSU/thermal/fan/SER/sensord not SW-controllable on Cisco); only needs skipping for 8102-64H-class HW. |
| `qos.test_buffer.test_buffer_deployment[<DUT>]` | vs 7050CX3 T0 | Dynamic buffer model not supported; Cisco-8000 only supports traditional. |
| `qos.test_tunnel_qos_remap.test_pfc_pause_extra_lossless_active[IPv4-<DUT>]`<br>`qos.test_tunnel_qos_remap.test_pfc_pause_extra_lossless_active[IPv6-<DUT>]`<br>`qos.test_tunnel_qos_remap.test_pfc_pause_extra_lossless_standby[IPv4-<DUT>]`<br>`qos.test_tunnel_qos_remap.test_pfc_pause_extra_lossless_standby[IPv6-<DUT>]` | vs 7050CX3 DualToR | Replacement relies on fanout-generated PFC frames (unreliable); confirm Cisco-proposed `test_pfc_watermark_extra_lossless_*` alternative. |


#### 🔴 Should be run/supported (real coverage gaps to address)

| Cases | Comparison | Reason |
| --- | --- | --- |
| `acl.custom_acl_table.test_custom_acl_table.test_custom_acl`<br>`acl.null_route.test_null_route_helper.test_null_route_helper`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_combined_tagged_dropped[ipv4]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_combined_tagged_dropped[ipv6]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_combined_tagged_forwarded[ipv4]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_combined_tagged_forwarded[ipv6]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_combined_untagged_dropped[ipv4]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_combined_untagged_dropped[ipv6]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_combined_untagged_forwarded[ipv4]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_combined_untagged_forwarded[ipv6]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_tagged_dropped[ipv4]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_tagged_dropped[ipv6]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_tagged_forwarded[ipv4]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_tagged_forwarded[ipv6]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_untagged_dropped[ipv4]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_untagged_dropped[ipv6]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_untagged_forwarded[ipv4]`<br>`acl.test_acl_outer_vlan.TestAclVlanOuter_Ingress.test_untagged_forwarded[ipv6]` | vs 7050CX3 T0 | 8200/Q200 does not support ACL match on outer VLAN; `custom_acl_table`/`null_route` run on T0 and pass. |
| `arp.test_tagged_arp.test_tagged_arp_pkt` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
| `bgp.test_bgp_update_replication.test_bgp_update_replication[<DUT>-default]` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
| `cacl.test_cacl_application.test_cacl_acl_loader[<DUT>]`<br>`cacl.test_cacl_application.test_cacl_acl_loader_commands_interval[<DUT>-None]`<br>`cacl.test_cacl_application.test_cacl_application_nondualtor[<DUT>-None]`<br>`cacl.test_cacl_application.test_cacl_scale_rules_ipv4[<DUT>]`<br>`cacl.test_cacl_application.test_cacl_scale_rules_ipv6[<DUT>]`<br>`cacl.test_cacl_application.test_caclmgrd_syslog[<DUT>]` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
| `copp.test_copp.TestCOPP.test_add_new_trap[<DUT>]`<br>`copp.test_copp.TestCOPP.test_remove_trap[<DUT>-delete_feature_entry]`<br>`copp.test_copp.TestCOPP.test_remove_trap[<DUT>-disable_feature_status]`<br>`copp.test_copp.TestCOPP.test_trap_config_save_after_reboot[<DUT>]`<br>`copp.test_copp.TestCOPP.test_trap_neighbor_miss[4-VlanSubnet-<DUT>]`<br>`copp.test_copp.TestCOPP.test_trap_neighbor_miss[4-VlanSubnetPinIP-<DUT>]`<br>`copp.test_copp.TestCOPP.test_trap_neighbor_miss[6-VlanSubnet-<DUT>]`<br>`copp.test_copp.TestCOPP.test_trap_neighbor_miss[6-VlanSubnetPinIP-<DUT>]` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
| `crm.test_crm.test_crm_fdb_entry[<DUT>-None]`<br>`crm.test_crm.test_crm_neighbor[<DUT>-2.2.2.1/8]`<br>`crm.test_crm.test_crm_neighbor[<DUT>-2001::2/64]`<br>`crm.test_crm.test_crm_nexthop[<DUT>-2.2.2.2]`<br>`crm.test_crm.test_crm_nexthop[<DUT>-2001::1]`<br>`crm.test_crm.test_crm_nexthop_group[<DUT>-2.2.2.0/24]` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
| `drop_packets.test_configurable_drop_counters.test_dip_link_local[PORT_INGRESS_DROPS-DIP_LINK_LOCAL]`<br>`drop_packets.test_configurable_drop_counters.test_neighbor_link_down[PORT_INGRESS_DROPS-L3_EGRESS_LINK_DOWN]`<br>`drop_packets.test_configurable_drop_counters.test_sip_link_local[PORT_INGRESS_DROPS-SIP_LINK_LOCAL]`<br>`drop_packets.test_drop_counters.test_dst_ip_absent[port_channel_members-<DUT>]`<br>`drop_packets.test_drop_counters.test_dst_ip_absent[vlan_members-<DUT>]`<br>`drop_packets.test_drop_counters.test_dst_ip_is_loopback_addr[port_channel_members-<DUT>]`<br>`drop_packets.test_drop_counters.test_dst_ip_is_loopback_addr[vlan_members-<DUT>]` | vs 7050CX3 DualToR | Q200 ASIC does not drop DIP/SIP link-local, dest-absent or loopback-addr packets. This is a **Cisco feature gap** — should be implemented/enabled, not skipped. |
| `dhcp_relay.test_dhcp_counter_stress.test_dhcpmon_relay_counters_stress[discover]`<br>`dhcp_relay.test_dhcp_counter_stress.test_dhcpmon_relay_counters_stress[request]`<br>`dhcp_relay.test_dhcp_relay.test_dhcp_relay_after_link_flap`<br>`dhcp_relay.test_dhcp_relay.test_dhcp_relay_after_link_flap[isc-relay-agent]`<br>`dhcp_relay.test_dhcp_relay.test_dhcp_relay_after_link_flap[sonic-relay-agent]`<br>`dhcp_relay.test_dhcp_relay.test_dhcp_relay_start_with_uplinks_down`<br>`dhcp_relay.test_dhcp_relay.test_dhcp_relay_start_with_uplinks_down[isc-relay-agent]`<br>`dhcp_relay.test_dhcp_relay.test_dhcp_relay_start_with_uplinks_down[sonic-relay-agent]`<br>`dhcp_relay.test_dhcpv6_relay.test_dhcp_relay_after_link_flap`<br>`dhcp_relay.test_dhcpv6_relay.test_dhcp_relay_start_with_uplinks_down` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
| `dualtor.test_orch_stress.test_change_mux_state`<br>`dualtor.test_orch_stress.test_flap_neighbor_entry_active`<br>`dualtor.test_orch_stress.test_flap_neighbor_entry_standby`<br>`dualtor.test_orchagent_active_tor_downstream.test_active_tor_remove_neighbor_downstream_active[ipv4]`<br>`dualtor.test_orchagent_active_tor_downstream.test_active_tor_remove_neighbor_downstream_active[ipv6]`<br>`dualtor.test_orchagent_active_tor_downstream.test_downstream_ecmp_nexthops[ipv4]`<br>`dualtor.test_orchagent_active_tor_downstream.test_downstream_ecmp_nexthops[ipv6]`<br>`dualtor.test_orchagent_mac_move.test_mac_move`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_downstream[ipv4]`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_downstream[ipv6]`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_downstream_bgp_recovered[ipv4]`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_downstream_bgp_recovered[ipv6]`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_downstream_loopback_route_readded[ipv4]`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_downstream_loopback_route_readded[ipv6]`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_downstream_t1_link_recovered[ipv4]`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_downstream_t1_link_recovered[ipv6]`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_remove_neighbor_downstream_standby[ipv4]`<br>`dualtor.test_orchagent_standby_tor_downstream.test_standby_tor_remove_neighbor_downstream_standby[ipv6]`<br>`dualtor.test_standby_tor_upstream_mux_toggle.test_standby_tor_upstream_mux_toggle` | vs 7050CX3 T0 | T0 mock-dualtor cases; run on T0 and pass. |
| `everflow.test_everflow_per_interface.test_everflow_per_interface[ipv6-erspan_ipv4-default]`<br>`everflow.test_everflow_per_interface.test_everflow_per_interface[ipv6-erspan_ipv6-default]`<br>`everflow.test_everflow_per_interface.test_everflow_packet_format[ipv6-erspan_ipv4-default]`<br>`everflow.test_everflow_per_interface.test_everflow_packet_format[ipv6-erspan_ipv6-default]` | vs 7050CX3 T0 | `IN_PORTS` match is not supported for `EVERFLOWV6` on this platform. This is a **Cisco feature gap** — should be implemented/enabled, not skipped. |
| `everflow.test_everflow_per_interface.test_everflow_per_interface[ipv4-erspan_ipv4-default]`<br>`everflow.test_everflow_per_interface.test_everflow_per_interface[ipv4-erspan_ipv6-default]`<br>`everflow.test_everflow_per_interface.test_everflow_packet_format[ipv4-erspan_ipv4-default]`<br>`everflow.test_everflow_per_interface.test_everflow_packet_format[ipv4-erspan_ipv6-default]` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
| `generic_config_updater.test_dynamic_acl.test_gcu_acl_arp_rule_creation[IPV4-<DUT>-None-default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_arp_rule_creation[IPV6-<DUT>-None-default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_dhcp_rule_creation[default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_drop_rule_creation[default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_drop_rule_removal[default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_forward_rule_priority_respected[default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_forward_rule_removal[default-Vlan1000-IPV4]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_forward_rule_removal[default-Vlan1000-IPV6]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_forward_rule_replacement[default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_forward_rule_same_priority[default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_nonexistent_rule_replacement[default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_nonexistent_table_removal[default-Vlan1000]`<br>`generic_config_updater.test_dynamic_acl.test_gcu_acl_scale_rules[default-Vlan1000]` | vs 7050CX3 DualToR | Skip condition removed; pass. |
| `generic_config_updater.test_monitor_config.test_monitor_config_tc1_suite[None]` | vs 7050CX3 DualToR | Skipped for "ERSPAN meter not supported", but **ERSPAN meter is now supported on Q200** — re-enable. |
| `metadata-scripts.test_metadata_bgp.test_bgp_traffic_shift_away[<DUT>-bgpsknat]`<br>`metadata-scripts.test_metadata_bgp.test_bgp_traffic_shift_away[<DUT>-forbidroutemap]`<br>`metadata-scripts.test_metadata_bgp.test_bgp_traffic_shift_away_timeout[<DUT>-bgpsknat]`<br>`metadata-scripts.test_metadata_bgp.test_bgp_traffic_shift_restore[<DUT>-bgpsknat]`<br>`metadata-scripts.test_metadata_bgp.test_bgp_traffic_shift_restore[<DUT>-forbidroutemap]`<br>`metadata-scripts.test_metadata_postupgrade.test_bgp_neighbors`<br>`metadata-scripts.test_metadata_postupgrade.test_postupgrade_actions`<br>`metadata-scripts.test_metadata_scripts.test_mirror_session_script` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
| `pc.test_lag_member.test_lag_member_status`<br>`pc.test_lag_member.test_lag_member_traffic` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
| `pfcwd.test_pfc_config.TestPfcConfig.test_forward_action_cfg[IPv4-<DUT>]`<br>`pfcwd.test_pfc_config.TestPfcConfig.test_forward_action_cfg[IPv6-<DUT>]` | vs 7050CX3 DualToR | PFC-WD `forward` action is a generic SONiC feature; skipped as "not supported on Q200". This is a **Cisco feature gap** — should be implemented/enabled, not skipped. |
| `pfcwd.test_pfcwd_all_port_storm.TestPfcwdAllPortStorm.test_all_port_storm_restore[IPv6-<DUT>]`<br>`pfcwd.test_pfcwd_cli.TestPfcwdFunc.test_pfcwd_show_stat[IPv6-<DUT>]`<br>`pfcwd.test_pfcwd_function.TestPfcwdFunc.test_pfcwd_actions[IPv6-<DUT>]`<br>`pfcwd.test_pfcwd_function.TestPfcwdFunc.test_pfcwd_mmu_change[IPv6-<DUT>]`<br>`pfcwd.test_pfcwd_function.TestPfcwdFunc.test_pfcwd_multi_port[IPv6-<DUT>]`<br>`pfcwd.test_pfcwd_function.TestPfcwdFunc.test_pfcwd_port_toggle[IPv6-<DUT>]`<br>`pfcwd.test_pfcwd_timer_accuracy.TestPfcwdAllTimer.test_pfcwd_timer_accuracy[IPv6-<DUT>]` | vs 7050CX3 DualToR | XFail (issue #21082) added for Mellanox and Cisco only; force-run and check actual behavior. |
| `qos.test_tunnel_qos_remap.test_separated_qos_map_on_tor` | vs 7050CX3 DualToR | Separated QoS map is not applied in Cisco-8000's dualtor config. |
| `vlan.test_vlan.test_vlan_tc3_send_invalid_vid` | vs 7050CX3 T0 | T0 case; runs on T0 and passes. |
