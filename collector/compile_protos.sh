#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/proto"
python -m grpc_tools.protoc -I. --python_out=. gtfs-realtime.proto nyct-subway.proto
# Fix relative import for generated nyct module
if grep -q '^import gtfs_realtime_pb2' nyct_subway_pb2.py 2>/dev/null; then
  sed -i.bak 's/^import gtfs_realtime_pb2/from . import gtfs_realtime_pb2/' nyct_subway_pb2.py || \
    sed -i '' 's/^import gtfs_realtime_pb2/from . import gtfs_realtime_pb2/' nyct_subway_pb2.py
  rm -f nyct_subway_pb2.py.bak
fi
echo "Compiled proto bindings in $(pwd)"
