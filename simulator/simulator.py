#!/usr/bin/env python3
"""Generate labeled simulated OT / IT / security telemetry for the MTA demo."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from elasticsearch import Elasticsearch, helpers

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("mta-simulator")

NATCA_SLA_DAYS = {"critical": 30, "high": 45, "medium": 60, "low": 180}
ALLOWLIST_IPS = {"203.0.113.10", "198.51.100.20", "10.50.1.5"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def base_labels(agency: str = "NYCT") -> dict[str, str]:
    return {"data_source": "simulated", "agency": agency, "demo": "mta-observability"}


def es_client() -> Elasticsearch:
    return Elasticsearch(
        os.environ["ES_URL"],
        api_key=os.environ["ES_API_KEY"],
        request_timeout=60,
        verify_certs=False,
        ssl_show_warn=False,
    )


def bulk(es: Elasticsearch, index: str, docs: list[dict[str, Any]]) -> int:
    actions = [{"_op_type": "create", "_index": index, "_source": d} for d in docs]
    if not actions:
        return 0
    ok, errors = helpers.bulk(es, actions, raise_on_error=False)
    if errors:
        LOG.warning("bulk errors: %s", errors[:1])
    return ok


def seed_assets(es: Elasticsearch) -> None:
    now = utc_now()
    assets = [
        {"asset.id": "ZC-7-01", "asset.name": "Zone Controller 7-01", "network.segment": "ot-cbtc-7", "agency": "NYCT"},
        {"asset.id": "DCS-AP-7-12", "asset.name": "Wayside AP 7-12", "network.segment": "ot-cbtc-7", "agency": "NYCT"},
        {"asset.id": "SCADA-TP-14", "asset.name": "Traction Power Substation 14", "network.segment": "ot-power", "agency": "NYCT"},
        {"asset.id": "PUMP-ET-03", "asset.name": "East Tube Pump Room 03", "network.segment": "ot-pump", "agency": "NYCT"},
        {"asset.id": "FW-IDMZ-01", "asset.name": "IDMZ Firewall 01", "network.segment": "idmz", "agency": "NYCT"},
        {"asset.id": "PLC-VENT-22", "asset.name": "Ventilation PLC 22", "network.segment": "ot-hvac", "agency": "NYCT"},
        {"asset.id": "LIRR-SW-04", "asset.name": "LIRR OT Switch 04", "network.segment": "ot-lirr", "agency": "LIRR"},
        {"asset.id": "MNR-RTU-09", "asset.name": "MNR RTU 09", "network.segment": "ot-mnr", "agency": "MNR"},
    ]
    docs = []
    for a in assets:
        docs.append(
            {
                "@timestamp": iso(now),
                "event": {"kind": "asset", "category": ["host"], "type": ["info"], "dataset": "mta.ot_asset"},
                "labels": base_labels(a["agency"]),
                "asset": {"id": a["asset.id"], "name": a["asset.name"]},
                "network": {"segment": a["network.segment"]},
                "host": {"name": a["asset.id"]},
                "message": f"known asset {a['asset.id']}",
            }
        )
    # Unknown device will be emitted during attack scenario
    LOG.info("seed assets %s", bulk(es, "logs-mta.ot_asset-simulated", docs))


def seed_vulns(es: Elasticsearch) -> None:
    now = utc_now()
    findings = [
        ("CVE-2024-1234", "critical", 40, "SCADA-TP-14"),
        ("CVE-2024-5678", "high", 20, "FW-IDMZ-01"),
        ("CVE-2023-9999", "medium", 70, "PLC-VENT-22"),
        ("CVE-2022-1111", "low", 200, "DCS-AP-7-12"),
        ("CVE-2024-2222", "critical", 10, "ZC-7-01"),
        ("CVE-2024-3333", "high", 50, "LIRR-SW-04"),
    ]
    docs = []
    for cve, sev, age_days, asset in findings:
        first = now - timedelta(days=age_days)
        deadline = first + timedelta(days=NATCA_SLA_DAYS[sev])
        overdue = now > deadline
        docs.append(
            {
                "@timestamp": iso(now),
                "event": {"kind": "alert", "category": ["vulnerability"], "type": ["info"], "dataset": "mta.vuln_finding"},
                "labels": base_labels("NYCT" if not asset.startswith("LIRR") else "LIRR"),
                "vulnerability": {
                    "id": cve,
                    "severity": sev,
                    "score": {"base": {"natca_sla_days": NATCA_SLA_DAYS[sev]}},
                },
                "transit": {
                    "vuln_age_days": age_days,
                    "vuln_sla_days": NATCA_SLA_DAYS[sev],
                    "vuln_overdue": overdue,
                    "vuln_days_overdue": max(0, (now - deadline).days) if overdue else 0,
                    "first_seen": iso(first),
                    "sla_deadline": iso(deadline),
                    "status": "open",
                },
                "host": {"name": asset},
                "message": f"{cve} {sev} on {asset} age={age_days}d overdue={overdue}",
            }
        )
    LOG.info("seed vulns %s", bulk(es, "logs-mta.vuln_finding-simulated", docs))


def seed_windows_ad(es: Elasticsearch) -> None:
    now = utc_now()
    docs = [
        {
            "@timestamp": iso(now - timedelta(minutes=5)),
            "event": {
                "kind": "event",
                "category": ["iam"],
                "type": ["change"],
                "action": "added-member-to-group",
                "code": "4728",
                "dataset": "windows.security",
            },
            "labels": base_labels("NYCT"),
            "user": {"name": "jsmith", "domain": "MTAOT"},
            "group": {"name": "Domain Admins"},
            "host": {"name": "DC01", "os": {"family": "windows"}},
            "message": "User jsmith added to Domain Admins",
            "transit": {"natca_function": "unauthorized_modification"},
        },
        {
            "@timestamp": iso(now - timedelta(minutes=12)),
            "event": {
                "kind": "event",
                "category": ["process"],
                "type": ["start"],
                "dataset": "windows.powershell",
            },
            "labels": base_labels("NYCT"),
            "process": {"name": "powershell.exe", "command_line": "powershell -enc SQBFAFgA..."},
            "user": {"name": "svc_backup", "domain": "MTAOT"},
            "host": {"name": "JUMP-OT-02", "os": {"family": "windows"}},
            "message": "Encoded PowerShell on jump host",
            "transit": {"natca_function": "unauthorized_system_intrusion"},
        },
        {
            "@timestamp": iso(now - timedelta(minutes=20)),
            "event": {
                "kind": "event",
                "category": ["authentication"],
                "type": ["start"],
                "dataset": "windows.security",
                "code": "4624",
            },
            "labels": base_labels("NYCT"),
            "user": {"name": "svc_scada", "domain": "MTAOT"},
            "logon": {"type": "Interactive"},
            "host": {"name": "ENG-WS-07"},
            "source": {"ip": "10.20.5.44"},
            "message": "Service account interactive logon",
            "transit": {"natca_function": "unexpected_remote_logon"},
        },
    ]
    LOG.info("seed windows/ad %s", bulk(es, "logs-mta.windows_ad-simulated", docs))


def emit_idmz_baseline(es: Elasticsearch) -> None:
    now = utc_now()
    docs = []
    for i in range(5):
        docs.append(
            {
                "@timestamp": iso(now - timedelta(seconds=i * 10)),
                "event": {"kind": "event", "category": ["network"], "type": ["connection", "allowed"], "dataset": "mta.idmz"},
                "labels": base_labels(),
                "source": {"ip": "10.30.1.20", "port": 55100 + i},
                "destination": {"ip": "10.40.2.15", "port": 502},
                "network": {"transport": "tcp", "protocol": "modbus", "direction": "inbound"},
                "modbus": {"function_code": 3, "function_name": "Read Holding Registers"},
                "observer": {"name": "FW-IDMZ-01", "type": "firewall"},
                "message": "Modbus read allowed",
                "tags": ["SIMULATED"],
            }
        )
    LOG.info("idmz baseline %s", bulk(es, "logs-mta.idmz-simulated", docs))


def emit_idmz_attack(es: Elasticsearch) -> None:
    """Replayable tabletop: Modbus write, PLC change, public NTP fallback, unknown asset, rogue remote access."""
    now = utc_now()
    docs_idmz = [
        {
            "@timestamp": iso(now),
            "event": {
                "kind": "alert",
                "category": ["network", "intrusion"],
                "type": ["denied", "connection"],
                "dataset": "mta.idmz",
                "severity": 80,
            },
            "labels": base_labels(),
            "source": {"ip": "10.10.50.12", "port": 54321},  # enterprise subnet
            "destination": {"ip": "10.40.2.15", "port": 502},
            "network": {
                "transport": "tcp",
                "protocol": "modbus",
                "direction": "inbound",
                "vlan": {"id": 30},
            },
            "modbus": {"function_code": 6, "function_name": "Write Single Register"},
            "observer": {"name": "FW-IDMZ-01", "type": "firewall"},
            "threat": {"framework": "MITRE ATT&CK for ICS", "technique": {"id": "T0855", "name": "Unauthorized Command Message"}},
            "transit": {"natca_function": "unauthorized_system_intrusion"},
            "message": "Modbus WRITE from enterprise subnet to PLC",
            "tags": ["SIMULATED", "ATTACK"],
        },
        {
            "@timestamp": iso(now + timedelta(seconds=30)),
            "event": {
                "kind": "alert",
                "category": ["configuration"],
                "type": ["change"],
                "dataset": "mta.idmz",
                "severity": 90,
            },
            "labels": base_labels(),
            "host": {"name": "PLC-VENT-22"},
            "user": {"name": "vendor_tech"},
            "transit": {
                "maintenance_window": False,
                "natca_function": "unauthorized_modification",
            },
            "threat": {"framework": "MITRE ATT&CK for ICS", "technique": {"id": "T0839", "name": "Module Firmware"}},
            "message": "PLC logic download outside maintenance window",
            "tags": ["SIMULATED", "ATTACK"],
        },
        {
            "@timestamp": iso(now + timedelta(seconds=60)),
            "event": {
                "kind": "alert",
                "category": ["network"],
                "type": ["protocol"],
                "dataset": "mta.idmz",
                "severity": 60,
            },
            "labels": base_labels(),
            "host": {"name": "ZC-7-01"},
            "dns": {"question": {"name": "pool.ntp.org"}},
            "network": {"protocol": "ntp"},
            "transit": {
                "ntp_source": "pool.ntp.org",
                "ntp_authenticated": False,
                "ntp_fallback": True,
                "natca_function": "unauthorized_communication",
            },
            "message": "Controller fell back to public unauthenticated NTP (last resort path)",
            "tags": ["SIMULATED", "ATTACK"],
        },
        {
            "@timestamp": iso(now + timedelta(seconds=45)),
            "event": {
                "kind": "alert",
                "category": ["network"],
                "type": ["info"],
                "dataset": "mta.idmz",
                "severity": 70,
            },
            "labels": base_labels(),
            "source": {"ip": "10.40.9.200"},
            "destination": {"ip": "10.40.2.1", "port": 502},
            "host": {"name": "UNKNOWN-10.40.9.200"},
            "network": {"segment": "ot-cbtc-7", "protocol": "modbus"},
            "transit": {"natca_function": "unauthorized_system_intrusion", "unknown_asset": True},
            "message": "Traffic from device not in OT asset inventory",
            "tags": ["SIMULATED", "ATTACK", "UNKNOWN_ASSET"],
        },
        {
            "@timestamp": iso(now + timedelta(seconds=90)),
            "event": {
                "kind": "alert",
                "category": ["network"],
                "type": ["start"],
                "dataset": "mta.idmz",
                "severity": 75,
            },
            "labels": base_labels(),
            "source": {"ip": "10.40.8.50"},
            "destination": {"ip": "10.40.8.1"},
            "network": {"protocol": "icmp", "bytes": 5000000},
            "transit": {"natca_function": "denial_of_service"},
            "message": "ICMP flood toward OT gateway (simulated DoS)",
            "tags": ["SIMULATED", "ATTACK"],
        },
        {
            "@timestamp": iso(now + timedelta(seconds=120)),
            "event": {
                "kind": "alert",
                "category": ["host"],
                "type": ["end"],
                "dataset": "mta.idmz",
                "severity": 65,
            },
            "labels": base_labels(),
            "host": {"name": "SCADA-TP-14"},
            "transit": {"natca_function": "unplanned_shutdown"},
            "message": "Unplanned substation controller restart",
            "tags": ["SIMULATED", "ATTACK"],
        },
    ]
    LOG.info("idmz attack %s", bulk(es, "logs-mta.idmz-simulated", docs_idmz))

    # Unknown asset inventory event
    unknown = {
        "@timestamp": iso(now + timedelta(seconds=45)),
        "event": {"kind": "asset", "category": ["host"], "type": ["info"], "dataset": "mta.ot_asset"},
        "labels": base_labels(),
        "asset": {"id": "UNKNOWN-10.40.9.200", "name": "Unregistered device"},
        "network": {"segment": "ot-cbtc-7"},
        "host": {"name": "UNKNOWN-10.40.9.200", "ip": "10.40.9.200"},
        "transit": {"inventory_status": "unknown", "natca_function": "unauthorized_system_intrusion"},
        "message": "Unknown asset discovered on OT segment",
        "tags": ["SIMULATED", "UNKNOWN_ASSET"],
    }
    bulk(es, "logs-mta.ot_asset-simulated", [unknown])

    # Vendor remote access violations
    remote_docs = [
        {
            "@timestamp": iso(now + timedelta(seconds=15)),
            "event": {
                "kind": "event",
                "category": ["authentication", "session"],
                "type": ["start"],
                "dataset": "mta.remote_access",
            },
            "labels": base_labels(),
            "source": {"ip": "198.51.100.99"},  # not allowlisted
            "user": {"name": "vendor_acme"},
            "client": {"type": "vpn"},
            "transit": {
                "vpn_allowlisted": False,
                "mfa_used": False,
                "session_idle_seconds": 0,
                "natca_function": "unexpected_remote_logon",
            },
            "threat": {"indicator": {"ip": "198.51.100.99"}},
            "message": "Vendor VPN login from non-allowlisted IP without MFA",
            "tags": ["SIMULATED", "ATTACK"],
        },
        {
            "@timestamp": iso(now + timedelta(minutes=8)),
            "event": {
                "kind": "event",
                "category": ["session"],
                "type": ["info"],
                "dataset": "mta.remote_access",
            },
            "labels": base_labels(),
            "source": {"ip": "203.0.113.10"},
            "user": {"name": "vendor_acme"},
            "transit": {
                "vpn_allowlisted": True,
                "mfa_used": True,
                "session_idle_seconds": 420,
                "idle_limit_seconds": 300,
                "natca_function": "unexpected_remote_logon",
            },
            "message": "Vendor remote session idle 420s exceeds 5 minute NATCA limit",
            "tags": ["SIMULATED", "ATTACK"],
        },
    ]
    LOG.info("remote access %s", bulk(es, "logs-mta.remote_access-simulated", remote_docs))

    # Netconfig change without ticket
    netcfg = {
        "@timestamp": iso(now + timedelta(seconds=75)),
        "event": {"kind": "event", "category": ["configuration"], "type": ["change"], "dataset": "mta.netconfig"},
        "labels": base_labels(),
        "host": {"name": "FW-IDMZ-01"},
        "user": {"name": "admin"},
        "transit": {"change_ticket": None, "natca_function": "unauthorized_modification"},
        "message": "Firewall ACL change with no matching change ticket",
        "tags": ["SIMULATED", "ATTACK"],
    }
    bulk(es, "logs-mta.netconfig-simulated", [netcfg])

    # Rogue AP
    wireless = {
        "@timestamp": iso(now + timedelta(seconds=100)),
        "event": {"kind": "alert", "category": ["network"], "type": ["info"], "dataset": "mta.wireless"},
        "labels": base_labels(),
        "wireless": {"ssid": "MTA-Free-WiFi", "bssid": "aa:bb:cc:dd:ee:ff", "rogue": True},
        "observer": {"name": "WLC-01"},
        "transit": {"natca_function": "unauthorized_system_intrusion"},
        "message": "Rogue AP detected near CBTC wayside",
        "tags": ["SIMULATED", "ATTACK"],
    }
    bulk(es, "logs-mta.wireless-simulated", [wireless])

    # Onboard HIDS
    onboard = {
        "@timestamp": iso(now + timedelta(seconds=110)),
        "event": {"kind": "alert", "category": ["malware", "intrusion"], "type": ["info"], "dataset": "mta.onboard"},
        "labels": base_labels(),
        "host": {"name": "TRAIN-R160-9241-GW"},
        "transit": {"natca_function": "unauthorized_system_intrusion", "rolling_stock": True},
        "message": "Onboard gateway HIDS alert: unexpected process",
        "tags": ["SIMULATED", "ATTACK"],
    }
    bulk(es, "logs-mta.onboard-simulated", [onboard])

    # CEF-style document (already normalized; documents CEF ingest path)
    cef = {
        "@timestamp": iso(now + timedelta(seconds=20)),
        "event": {
            "kind": "event",
            "category": ["network"],
            "type": ["denied"],
            "dataset": "cef.log",
            "original": "CEF:0|MTA-Sim|IDMZ-FW|1.0|400|Modbus Write Denied|8|src=10.10.50.12 dst=10.40.2.15 proto=TCP spt=54321 dpt=502",
        },
        "labels": base_labels(),
        "cef": {"version": "0", "device_vendor": "MTA-Sim", "device_product": "IDMZ-FW", "severity": 8},
        "source": {"ip": "10.10.50.12"},
        "destination": {"ip": "10.40.2.15", "port": 502},
        "message": "CEF Modbus Write Denied",
        "tags": ["SIMULATED", "CEF"],
    }
    bulk(es, "logs-cef.log-simulated", [cef])

    # Threat intel matchable indicator
    ti = {
        "@timestamp": iso(now),
        "event": {"kind": "enrichment", "category": ["threat"], "type": ["indicator"], "dataset": "mta.threat_intel"},
        "labels": base_labels(),
        "threat": {
            "indicator": {
                "type": "ipv4-addr",
                "ip": "198.51.100.99",
                "name": "ICS-advisory-simulated-c2",
                "confidence": 80,
                "provider": "demo-ti",
            },
            "framework": "ICS Advisory (simulated)",
        },
        "message": "IOC 198.51.100.99 — simulated ICS advisory C2",
        "tags": ["SIMULATED", "THREAT_INTEL"],
    }
    bulk(es, "logs-mta.threat_intel-simulated", [ti])

    # OT metrics snippets for storm / DCS stories
    metrics = []
    for i in range(12):
        t = now - timedelta(minutes=5 * (11 - i))
        metrics.append(
            {
                "@timestamp": iso(t),
                "event": {"dataset": "mta.ot_pump"},
                "labels": base_labels(),
                "host": {"name": "PUMP-ET-03"},
                "metrics": {
                    "ot.pump.sump_level_ft": 2.0 + i * 0.35 + random.uniform(-0.05, 0.05),
                    "ot.pump.runtime_hours": 1200 + i,
                },
                "tags": ["SIMULATED"],
            }
        )
        metrics.append(
            {
                "@timestamp": iso(t),
                "event": {"dataset": "mta.ot_dcs"},
                "labels": base_labels(),
                "host": {"name": "DCS-AP-7-12"},
                "transit": {"route_id": "7"},
                "metrics": {
                    "ot.dcs.rtt_ms": 40 + i * 8 + random.uniform(0, 5),
                    "ot.dcs.handover_ms": 10 + i * 2,
                },
                "tags": ["SIMULATED"],
                "message": "Simulated DCS latency sample (no vendor threshold claimed)",
            }
        )
    bulk(es, "metrics-mta.ot_pump-simulated", [m for m in metrics if m["event"]["dataset"] == "mta.ot_pump"])
    bulk(es, "metrics-mta.ot_dcs-simulated", [m for m in metrics if m["event"]["dataset"] == "mta.ot_dcs"])


def write_syslog_line(host: str, port: int, msg: str) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(msg.encode("utf-8"), (host, port))
    finally:
        sock.close()


def run_loop(interval: int, attack_every: int) -> None:
    es = es_client()
    seed_assets(es)
    seed_vulns(es)
    seed_windows_ad(es)
    n = 0
    while True:
        emit_idmz_baseline(es)
        if n > 0 and n % attack_every == 0:
            LOG.info("emitting attack scenario")
            emit_idmz_attack(es)
        n += 1
        time.sleep(interval)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Seed + one attack burst then exit")
    p.add_argument("--seed-only", action="store_true")
    p.add_argument("--attack", action="store_true", help="Emit attack scenario once")
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--attack-every", type=int, default=10, help="Emit attack every N baseline loops")
    args = p.parse_args()
    es = es_client()
    if args.seed_only:
        seed_assets(es)
        seed_vulns(es)
        seed_windows_ad(es)
        emit_idmz_baseline(es)
        return
    if args.attack or args.once:
        seed_assets(es)
        seed_vulns(es)
        seed_windows_ad(es)
        emit_idmz_baseline(es)
        emit_idmz_attack(es)
        return
    run_loop(args.interval, args.attack_every)


if __name__ == "__main__":
    main()
