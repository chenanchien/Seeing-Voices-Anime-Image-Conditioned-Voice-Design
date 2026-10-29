#!/usr/bin/env bash
# Resume the data pipelines after the computer was shut down or the run was interrupted.
# Every step skips finished work (existing files, cached rows), so this is always safe to rerun.
#
#   nohup caffeinate -i scripts/resume.sh > data/logs/resume.log 2>&1 &
#
# Games resumed here already have complete manifests, so adapters are NOT rerun
# (no new wiki crawling). See docs/STATUS.md for what is done and what is pending.
set -u
cd "$(dirname "$0")/.."
P=.venv/bin/python
mkdir -p data/logs

GAMES=(fgo arknights bluearchive)

run_game() {
  local g=$1
  echo "=== resume $(date) ===" >> "data/logs/${g}_full.log"
  ( $P -m src.download "$g" && $P -m src.clean.audio "$g" && $P -m src.clean.langid "$g" \
    && $P -m src.clean.finalize "$g" && echo PIPELINE_DONE ) >> "data/logs/${g}_full.log" 2>&1
}

for g in "${GAMES[@]}"; do run_game "$g" & done
wait

$P -m src.sources.fgo --profiles-only   # profile text from the cached Atlas export, no network
$P -m src.clean.voice_actors
$P -m src.report
echo "ALL DONE $(date)"
