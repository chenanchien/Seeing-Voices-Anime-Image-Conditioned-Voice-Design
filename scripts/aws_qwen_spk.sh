#!/bin/bash
# Per-clip Qwen speaker embeddings (data/embeddings/qwen-spk) on an AWS GPU machine, from the
# data on Delta. rsync asks for the NCSA password + Duo; rerun the script after any interruption
# (downloads resume, finished games are skipped).
#
#   DELTA_USER=pchang5 bash aws_qwen_spk.sh
set -euo pipefail
DELTA_USER=${DELTA_USER:-pchang5}
SRC=$DELTA_USER@login.delta.ncsa.illinois.edu:/work/hdd/bjop/kchien
WORK=${WORK:-$HOME}

# 1. both halves are needed: arknights / azurlane / fgo exist only as files under
#    seeing-voices/data/processed, five games only inside sv-share tars (the script reads both)
rsync -a --partial --info=progress2 "$SRC/seeing-voices/" "$WORK/seeing-voices/"
rsync -a --partial --info=progress2 "$SRC/sv-share/" --include='seeing-voices_*.tar' --exclude='*' "$WORK/sv-share/"

# 2. environment
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH=$HOME/.local/bin:$PATH; }
cd "$WORK/seeing-voices"
[ -d .venv ] || uv venv -p 3.12
. .venv/bin/activate
uv pip install -q qwen-tts soundfile

# 3. every game must report 0 usable clips without audio, else rerun step 1
python -m src.embed_qwen --list-missing --tars "$WORK/sv-share" 2>&1 | tee missing.log
if grep "without audio" missing.log | grep -qv " 0 usable"; then
  echo "audio incomplete: rerun this script to resume the download"; exit 1
fi

# 4. reproduce Tianxiang's prototypes (cosine ~1, norm ratio ~1.0 in the last line), then all clips
python -m src.embed_qwen --check --tars "$WORK/sv-share"
python -m src.embed_qwen --tars "$WORK/sv-share"
ls -la data/embeddings/qwen-spk/
