#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
# shellcheck disable=SC1091
source .env
set +a
source .venv/bin/activate
bash collector/compile_protos.sh
python elastic/scripts/bootstrap_cluster.py
python scripts/validate_feeds.py
python collector/refdata.py
python elastic/scripts/setup_enrich.py
python simulator/simulator.py --once
python elastic/scripts/import_kibana_objects.py
python elastic/scripts/create_detection_rules.py
python elastic/scripts/create_tabletop_case.py
python elastic/scripts/setup_ml_job.py || true
echo "Bootstrap done. Start live ingest:"
echo "  python collector/collector.py"
echo "  python simulator/simulator.py --interval 120 --attack-every 5"
echo "Open: $KIBANA_URL/s/mta-demo"
