# NATCA 22.2.6 — Log pipeline health

Create Kibana threshold / ES|QL alert rules in Space `mta-demo`:

## No-data per source (examples)

1. **Subway trips silent**
   - Index: `logs-mta.subway_trip-*`
   - Condition: count == 0 over last 5 minutes
   - Filter: `labels.feed_id: subway_1234567S`

2. **IDMZ concentrator silent**
   - Index: `logs-mta.idmz-*`
   - Condition: count == 0 over last 10 minutes
   - Filter: `labels.data_source: simulated`

3. **E&E snapshot stale**
   - Index: `metrics-mta.ene_status-*`
   - Condition: count == 0 over last 15 minutes

## Storage threshold

Use Stack Monitoring or a cluster alert when data stream store size exceeds demo budget (e.g. 50 GB for `logs-mta.*`).

## Ingest failures

Watch `_ingest` / failed docs via:
```esql
FROM logs-mta.*
| WHERE event.kind == "pipeline_error"
| STATS c = COUNT(*) BY event.dataset
```
(Collector also logs bulk errors to stdout for ops.)
