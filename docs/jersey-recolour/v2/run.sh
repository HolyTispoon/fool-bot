#!/usr/bin/env bash
# Rebuilds the v2 pilot portraits into out/. Run from the repository root.
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd); K=$D/../kit; W=$(mktemp -d)
export PYTHONWARNINGS=ignore
cp "$K/kit.py" "$K/generic.py" "$K/refs.pkl" "$D"/*.py "$W/"
python3 "$W/p_quantor.py" "$W"
python3 "$W/generic.py" "$W" Gearclaw black '[[[118,100],[128,90],[165,58],[200,55],[200,98],[215,104],[240,100],[255,120],[250,175],[200,190],[150,182],[126,152],[121,125]]]' '[[[200,62],[210,52],[232,50],[242,58],[245,75],[243,95],[235,100],[215,102],[203,98],[200,80]],[[96,100],[121,100],[123,120],[121,142],[98,146]]]'
python3 "$W/p_ozul.py" "$W"
python3 "$W/p_hellguard.py" "$W"
python3 "$W/p_kindle.py" "$W"
python3 "$W/p_zenith.py" "$W"
python3 "$W/p_zenith_foot.py" "$W" 93 0.8
python3 "$W/p_umbrik.py" "$W"
mkdir -p "$D/out"
for f in Quantor_purple Gearclaw_black Ozul_teal Hellguard_purple Kindlefinger_teal Zenith_teal Zenith_teal_foot Umbrik_black; do
  cp "$W/$f.png" "$D/out/"
done
rm -rf "$W"
