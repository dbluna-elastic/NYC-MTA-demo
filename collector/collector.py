#!/usr/bin/env python3
"""MTA public feed collector → Elasticsearch data streams."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from elasticsearch import Elasticsearch, helpers

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = logging.getLogger("mta-collector")

# Ensure compiled protos exist
PROTO_DIR = ROOT / "proto"
if not (PROTO_DIR / "gtfs_realtime_pb2.py").exists():
    import subprocess

    subprocess.check_call(["bash", str(ROOT / "compile_protos.sh")])

from proto import gtfs_realtime_pb2 as gtfs_rt  # noqa: E402
from proto import nyct_subway_pb2 as nyct  # noqa: E402


def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None or val == "":
        raise SystemExit(f"Missing required env var: {name}")
    return val


def load_feeds() -> dict[str, Any]:
    with open(ROOT / "feeds.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def enabled_feed_ids() -> set[str]:
    raw = os.environ.get("COLLECTOR_ENABLED_FEEDS", "subway_1234567S")
    return {x.strip() for x in raw.split(",") if x.strip()}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def feed_ts_iso(header_ts: int) -> str:
    return datetime.fromtimestamp(header_ts, tz=timezone.utc).isoformat()


def doc_fingerprint(doc: dict[str, Any], keys: list[str]) -> str:
    payload = {k: doc.get(k) for k in keys}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


class Collector:
    def __init__(self) -> None:
        self.es_url = env("ES_URL")
        self.es = Elasticsearch(
            self.es_url,
            api_key=env("ES_API_KEY"),
            request_timeout=60,
            verify_certs=False,
            ssl_show_warn=False,
        )
        self.poll = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
        self.feeds_cfg = load_feeds()
        self.enabled = enabled_feed_ids()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "mta-observability-demo/1.0"})
        # trip_id -> last fingerprint
        self._trip_state: dict[str, str] = {}
        self._trip_stop: dict[str, str] = {}  # trip_id -> last current_stop for arrival derivation
        self._alert_state: dict[str, str] = {}
        self._ene_state: dict[str, str] = {}
        self._last_header_ts: dict[str, int] = {}

    def all_feed_entries(self) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        for section in ("subway", "railroad", "alerts", "ene"):
            for fid, cfg in (self.feeds_cfg.get(section) or {}).items():
                if fid in self.enabled:
                    out.append((fid, cfg))
        return out

    def fetch_bytes(self, url: str) -> bytes:
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return r.content

    def fetch_json(self, url: str) -> Any:
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return r.json()

    def bulk_index(self, actions: list[dict[str, Any]]) -> int:
        if not actions:
            return 0
        ok, errors = helpers.bulk(self.es, actions, raise_on_error=False, request_timeout=120)
        if errors:
            LOG.warning("bulk had %s errors (showing first): %s", len(errors), errors[:1])
        return ok

    # --- subway / railroad GTFS-RT ---

    def parse_subway_trips(self, feed_id: str, raw: bytes) -> list[dict[str, Any]]:
        msg = gtfs_rt.FeedMessage()
        msg.ParseFromString(raw)
        header_ts = int(msg.header.timestamp) if msg.header.timestamp else int(time.time())
        prev = self._last_header_ts.get(feed_id)
        if prev is not None and header_ts <= prev:
            LOG.warning("stale feed %s header_ts=%s prev=%s", feed_id, header_ts, prev)
        self._last_header_ts[feed_id] = header_ts
        ts_iso = feed_ts_iso(header_ts)
        ingested = utc_now_iso()
        docs: list[dict[str, Any]] = []

        for ent in msg.entity:
            if not ent.HasField("trip_update"):
                continue
            tu = ent.trip_update
            trip = tu.trip
            route_id = trip.route_id or ""
            trip_id = trip.trip_id or ent.id
            direction = ""
            train_id = ""
            is_assigned = None
            if trip.HasExtension(nyct.nyct_trip_descriptor):
                ny = trip.Extensions[nyct.nyct_trip_descriptor]
                train_id = ny.train_id or ""
                is_assigned = bool(ny.is_assigned) if ny.HasField("is_assigned") else None
                # direction enum: NORTH=1 SOUTH=3 etc — store as int/string
                if ny.HasField("direction"):
                    direction = str(ny.direction)

            # Current / next stop from first two stop_time_updates
            stop_updates = list(tu.stop_time_update)
            current_stop = stop_updates[0].stop_id if stop_updates else None
            next_stop = stop_updates[1].stop_id if len(stop_updates) > 1 else None
            scheduled_track = None
            actual_track = None
            track_diverted = False
            if stop_updates:
                stu = stop_updates[0]
                if stu.HasExtension(nyct.nyct_stop_time_update):
                    nstu = stu.Extensions[nyct.nyct_stop_time_update]
                    scheduled_track = nstu.scheduled_track or None
                    actual_track = nstu.actual_track or None
                    if scheduled_track and actual_track and scheduled_track != actual_track:
                        track_diverted = True

            doc = {
                "@timestamp": ts_iso,
                "event": {
                    "ingested": ingested,
                    "dataset": "mta.subway_trip",
                    "kind": "event",
                    "category": ["transport"],
                    "type": ["info"],
                },
                "labels": {
                    "data_source": "real",
                    "feed_id": feed_id,
                    "agency": "NYCT",
                },
                "observer": {"vendor": "MTA", "product": "GTFS-RT"},
                "transit": {
                    "route_id": route_id,
                    "trip_id": trip_id,
                    "train_id": train_id,
                    "direction": direction,
                    "is_assigned": is_assigned,
                    "current_stop_id": current_stop,
                    "next_stop_id": next_stop,
                    "scheduled_track": scheduled_track,
                    "actual_track": actual_track,
                    "track_diverted": track_diverted,
                    "stop_update_count": len(stop_updates),
                },
                "message": f"trip {trip_id} route {route_id} stop {current_stop}",
            }
            fp_keys = [
                "transit.route_id",
                "transit.trip_id",
                "transit.train_id",
                "transit.current_stop_id",
                "transit.actual_track",
                "transit.track_diverted",
                "transit.is_assigned",
            ]
            # flatten for fingerprint
            flat = {
                "transit.route_id": route_id,
                "transit.trip_id": trip_id,
                "transit.train_id": train_id,
                "transit.current_stop_id": current_stop,
                "transit.actual_track": actual_track,
                "transit.track_diverted": track_diverted,
                "transit.is_assigned": is_assigned,
            }
            fp = doc_fingerprint(flat, fp_keys)
            state_key = f"{feed_id}:{trip_id}"
            prev_stop = self._trip_stop.get(state_key)
            if prev_stop and current_stop and prev_stop != current_stop:
                # Derived arrival: train left prev_stop
                arrival = {
                    "@timestamp": ts_iso,
                    "event": {
                        "ingested": ingested,
                        "dataset": "mta.subway_arrival",
                        "kind": "event",
                        "category": ["transport"],
                        "type": ["info"],
                    },
                    "labels": {
                        "data_source": "real",
                        "feed_id": feed_id,
                        "agency": "NYCT",
                    },
                    "transit": {
                        "route_id": route_id,
                        "trip_id": trip_id,
                        "train_id": train_id,
                        "stop_id": prev_stop,
                        "next_stop_id": current_stop,
                        "scheduled_track": scheduled_track,
                        "actual_track": actual_track,
                        "track_diverted": track_diverted,
                    },
                    "message": f"arrival derived trip {trip_id} left {prev_stop}",
                }
                docs.append(arrival)
            if current_stop:
                self._trip_stop[state_key] = current_stop
            if self._trip_state.get(state_key) == fp:
                continue
            self._trip_state[state_key] = fp
            docs.append(doc)
        return docs

    def parse_railroad_trips(self, feed_id: str, cfg: dict[str, Any], raw: bytes) -> list[dict[str, Any]]:
        msg = gtfs_rt.FeedMessage()
        msg.ParseFromString(raw)
        header_ts = int(msg.header.timestamp) if msg.header.timestamp else int(time.time())
        self._last_header_ts[feed_id] = header_ts
        ts_iso = feed_ts_iso(header_ts)
        ingested = utc_now_iso()
        agency = cfg.get("agency", feed_id.upper())
        docs: list[dict[str, Any]] = []
        for ent in msg.entity:
            if not ent.HasField("trip_update"):
                continue
            tu = ent.trip_update
            trip = tu.trip
            trip_id = trip.trip_id or ent.id
            route_id = trip.route_id or ""
            stop_updates = list(tu.stop_time_update)
            current_stop = stop_updates[0].stop_id if stop_updates else None
            # railroad feeds often put track in stop_time_update.schedule_relationship / vehicle
            track = None
            train_status = None
            if stop_updates and stop_updates[0].HasField("arrival"):
                pass
            # MTA railroad extension fields appear as vehicle or trip attributes in practice;
            # capture schedule_relationship as status proxy when present.
            if trip.schedule_relationship:
                train_status = gtfs_rt.TripDescriptor.ScheduleRelationship.Name(trip.schedule_relationship)

            doc = {
                "@timestamp": ts_iso,
                "event": {
                    "ingested": ingested,
                    "dataset": "mta.railroad_trip",
                    "kind": "event",
                    "category": ["transport"],
                    "type": ["info"],
                },
                "labels": {
                    "data_source": "real",
                    "feed_id": feed_id,
                    "agency": agency,
                },
                "observer": {"vendor": "MTA", "product": "GTFS-RT"},
                "transit": {
                    "route_id": route_id,
                    "trip_id": trip_id,
                    "current_stop_id": current_stop,
                    "track": track,
                    "train_status": train_status,
                    "stop_update_count": len(stop_updates),
                },
                "message": f"{agency} trip {trip_id} route {route_id}",
            }
            flat = {
                "trip_id": trip_id,
                "current_stop": current_stop,
                "status": train_status,
            }
            fp = doc_fingerprint(flat, list(flat.keys()))
            state_key = f"{feed_id}:{trip_id}"
            if self._trip_state.get(state_key) == fp:
                continue
            self._trip_state[state_key] = fp
            docs.append(doc)
        return docs

    def parse_alerts(self, feed_id: str, raw: bytes) -> list[dict[str, Any]]:
        msg = gtfs_rt.FeedMessage()
        msg.ParseFromString(raw)
        header_ts = int(msg.header.timestamp) if msg.header.timestamp else int(time.time())
        ts_iso = feed_ts_iso(header_ts)
        ingested = utc_now_iso()
        docs: list[dict[str, Any]] = []
        for ent in msg.entity:
            if not ent.HasField("alert"):
                continue
            alert = ent.alert
            header_text = ""
            description = ""
            if alert.header_text.translation:
                header_text = alert.header_text.translation[0].text
            if alert.description_text.translation:
                description = alert.description_text.translation[0].text
            routes = []
            stops = []
            for ie in alert.informed_entity:
                if ie.route_id:
                    routes.append(ie.route_id)
                if ie.stop_id:
                    stops.append(ie.stop_id)
            active = []
            for ap in alert.active_period:
                active.append(
                    {
                        "start": ap.start or None,
                        "end": ap.end or None,
                    }
                )
            cause = gtfs_rt.Alert.Cause.Name(alert.cause) if alert.cause else None
            effect = gtfs_rt.Alert.Effect.Name(alert.effect) if alert.effect else None
            doc = {
                "@timestamp": ts_iso,
                "event": {
                    "ingested": ingested,
                    "dataset": "mta.alert",
                    "kind": "alert",
                    "category": ["transport"],
                    "type": ["info"],
                    "cause": cause,
                    "action": effect,
                },
                "labels": {"data_source": "real", "feed_id": feed_id, "agency": "MTA"},
                "transit": {
                    "alert_id": ent.id,
                    "header": header_text,
                    "description": description[:4000] if description else "",
                    "route_ids": routes,
                    "stop_ids": stops,
                    "active_period": active,
                },
                "message": header_text or ent.id,
            }
            fp = doc_fingerprint(
                {"id": ent.id, "header": header_text, "routes": routes},
                ["id", "header", "routes"],
            )
            if self._alert_state.get(ent.id) == fp:
                continue
            self._alert_state[ent.id] = fp
            docs.append(doc)
        return docs

    def parse_ene(self, feed_id: str, data: Any) -> list[dict[str, Any]]:
        ingested = utc_now_iso()
        ts_iso = ingested
        items = data if isinstance(data, list) else data.get("results") or data.get("equipments") or []
        if isinstance(data, dict) and "nyct_ene" in data:
            items = data["nyct_ene"]
        # Current outages feed is often a list of outage objects
        if isinstance(data, dict):
            for key in ("outages", "upcoming", "equipments"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
        docs: list[dict[str, Any]] = []
        if not isinstance(items, list):
            LOG.warning("unexpected ene payload type for %s: %s", feed_id, type(data))
            return docs
        for item in items:
            if not isinstance(item, dict):
                continue
            eq_id = str(
                item.get("equipment")
                or item.get("equipmentid")
                or item.get("equipment_id")
                or item.get("stationelevatorid")
                or item.get("isada")
                or ""
            )
            # nyct_ene.json structure: station, borough, trainno, equipment, equipmenttype, serving, ADA, outagedate, estimatedreturntoservice, reason
            if not eq_id:
                eq_id = str(item.get("equipment", item.get("EquipmentID", "")))
            reason = item.get("reason") or item.get("Reason") or ""
            station = item.get("station") or item.get("Station") or ""
            eq_type = item.get("equipmenttype") or item.get("equipmentType") or item.get("type") or ""
            in_service = 0  # outage feed = not in service
            if feed_id == "ene_equipments":
                in_service = 1
            doc = {
                "@timestamp": ts_iso,
                "event": {
                    "ingested": ingested,
                    "dataset": "mta.ene_status",
                    "kind": "metric",
                    "category": ["transport"],
                },
                "labels": {"data_source": "real", "feed_id": feed_id, "agency": "NYCT"},
                "equipment": {"id": eq_id},
                "transit": {
                    "station_name": station,
                    "borough": item.get("borough") or item.get("Borough"),
                    "lines": item.get("trainno") or item.get("train_no") or item.get("lines"),
                    "equipment_type": eq_type,
                    "serving": item.get("serving") or item.get("Serving"),
                    "ada": item.get("ADA") or item.get("ada"),
                    "outage_date": item.get("outagedate") or item.get("OutageDate"),
                    "estimated_return": item.get("estimatedreturntoservice")
                    or item.get("EstimatedReturnToService"),
                    "reason": reason,
                    "ene_in_service": in_service,
                },
                "metrics": {"ene.in_service": in_service},
                "message": f"{eq_type} {eq_id} at {station}: {reason or 'status'}",
            }
            fp = doc_fingerprint(
                {"eq": eq_id, "reason": reason, "ret": doc["transit"]["estimated_return"]},
                ["eq", "reason", "ret"],
            )
            state_key = f"{feed_id}:{eq_id}:{reason}"
            if self._ene_state.get(state_key) == fp:
                continue
            self._ene_state[state_key] = fp
            docs.append(doc)
        return docs

    def poll_once(self) -> None:
        actions: list[dict[str, Any]] = []
        for feed_id, cfg in self.all_feed_entries():
            kind = cfg["kind"]
            url = cfg["url"]
            try:
                if kind == "subway_gtfsrt":
                    raw = self.fetch_bytes(url)
                    docs = self.parse_subway_trips(feed_id, raw)
                elif kind == "railroad_gtfsrt":
                    raw = self.fetch_bytes(url)
                    docs = self.parse_railroad_trips(feed_id, cfg, raw)
                elif kind == "alerts_gtfsrt":
                    raw = self.fetch_bytes(url)
                    docs = self.parse_alerts(feed_id, raw)
                elif kind in ("ene_json", "ene_equipments"):
                    data = self.fetch_json(url)
                    docs = self.parse_ene(feed_id, data)
                else:
                    LOG.debug("skip unsupported kind %s", kind)
                    continue
                for d in docs:
                    dataset = (d.get("event") or {}).get("dataset", "")
                    if dataset == "mta.subway_arrival":
                        index = "logs-mta.subway_arrival-default"
                    elif dataset == "mta.subway_trip":
                        index = "logs-mta.subway_trip-default"
                    elif dataset == "mta.railroad_trip":
                        index = "logs-mta.railroad_trip-default"
                    elif dataset == "mta.alert":
                        index = "logs-mta.alert-default"
                    elif dataset == "mta.ene_status":
                        index = "metrics-mta.ene_status-default"
                    else:
                        index = "logs-mta.subway_trip-default"
                    actions.append({"_op_type": "create", "_index": index, "_source": d})
                LOG.info("feed %s → %s docs", feed_id, len(docs))
            except Exception:
                LOG.exception("feed %s failed", feed_id)

        n = self.bulk_index(actions)
        LOG.info("indexed %s documents", n)

    def run(self) -> None:
        LOG.info("starting collector feeds=%s poll=%ss", sorted(self.enabled), self.poll)
        # sanity
        info = self.es.info()
        LOG.info("elasticsearch %s", info.get("version", {}).get("number"))
        while True:
            self.poll_once()
            time.sleep(self.poll)


def main() -> None:
    import argparse

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Poll all enabled feeds once and exit")
    args = p.parse_args()
    c = Collector()
    if args.once:
        info = c.es.info()
        LOG.info("elasticsearch %s", info.get("version", {}).get("number"))
        c.poll_once()
        return
    c.run()


if __name__ == "__main__":
    main()
