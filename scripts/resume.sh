#!/usr/bin/env bash
# Resume the data pipelines after the computer was shut down or the run was interrupted.
# Every step skips finished work (existing files, cached rows), so this is always safe to rerun.
#
#   nohup scripts/resume.sh > data/logs/resume.log 2>&1 &
#
# The script keeps the Mac awake itself (caffeinate) for as long as it runs. Closing the lid
# without an external display still forces sleep, so leave the lid open.
#
# FGO / Arknights / Blue Archive already have complete manifests, so their adapters are NOT
# rerun (no new wiki crawling). Genshin / Star Rail / WuWa adapters run once until
# data/raw/<game>/.adapter_full_done exists. See docs/STATUS.md for what is done and what is pending.
set -u
cd "$(dirname "$0")/.."
P=.venv/bin/python
mkdir -p data/logs

# -i idle sleep, -m disk sleep, -s system sleep (on AC power); released when this script exits
caffeinate -ims -w $$ &

GAMES=(fgo arknights bluearchive genshin starrail wuwa)
HF_GAMES=(genshin starrail wuwa)  # adapters are cheap (HoYoLAB / encore.moe JSON): rerun until a full build is marked done

run_game() {
  local g=$1
  echo "=== resume $(date) ===" >> "data/logs/${g}_full.log"
  [[ " ${HF_GAMES[*]} " == *" $g "* && ! -f "data/raw/$g/.adapter_full_done" ]] && return  # adapter failed
  ( $P -m src.download "$g" && $P -m src.clean.audio "$g" && $P -m src.clean.langid "$g" \
    && $P -m src.clean.finalize "$g" && echo PIPELINE_DONE ) >> "data/logs/${g}_full.log" 2>&1
}

# HF-game adapters first and one at a time (genshin + starrail share the HoYoLAB host)
for g in "${HF_GAMES[@]}"; do
  if [[ ! -f "data/raw/$g/.adapter_full_done" ]]; then
    $P -m src.sources.hfgames "$g" >> "data/logs/${g}_full.log" 2>&1 && touch "data/raw/$g/.adapter_full_done"
  fi
done

for g in "${GAMES[@]}"; do run_game "$g" & done
wait

$P -m src.sources.fgo --profiles-only   # profile text from the cached Atlas export, no network
$P -m src.clean.voice_actors
$P -m src.report
echo "ALL DONE $(date)"
