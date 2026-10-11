#!/usr/bin/env bash
# Rebuilds the v1 pilot portraits into out/. Run from the repository root.
# Quantor to Kindlefinger were made before the teal model was resampled
# from the native shirts alone, so they run on the first models.
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd); K=$D/../kit; W=$(mktemp -d)
export PYTHONWARNINGS=ignore
cp "$K/kit.py" "$K/generic.py" "$D"/*.py "$W/"
cp "$D/refs_first_teal.pkl" "$W/refs.pkl"
python3 "$W/p_quantor.py" "$W"
python3 "$W/generic.py" "$W" Gearclaw black '[[[128,95],[165,58],[205,55],[245,65],[255,120],[250,175],[200,190],[150,182],[130,140]]]' '[[[214,72],[242,72],[242,100],[214,100]]]'
python3 "$W/dark.py" "$W" Ozul teal '[[[160,140],[180,112],[205,105],[250,100],[300,104],[340,112],[358,150],[345,200],[300,220],[230,222],[185,210],[163,170]]]' '[[[207,100],[247,98],[250,125],[238,142],[213,142]],[[249,106],[276,106],[278,134],[250,136]]]' 30 24
python3 "$W/p_hellguard.py" "$W"
python3 "$W/p_kindle.py" "$W"
cp "$K/refs.pkl" "$W/refs.pkl"
python3 "$W/p_zenith.py" "$W"
python3 "$W/p_umbrik.py" "$W"
mkdir -p "$D/out"
for f in Quantor_purple Gearclaw_black Ozul_teal Hellguard_purple Kindlefinger_teal Zenith_teal Umbrik_black; do
  cp "$W/$f.png" "$D/out/"
done
rm -rf "$W"
