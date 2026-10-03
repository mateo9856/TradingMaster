#!/usr/bin/env bash
#
# Prints a short content hash of everything that goes into the Docker images.
#
# WHY THIS EXISTS
# ---------------
# `docker compose up -d` reuses any image that already carries the tag the
# compose file asks for. It does not look at your source. So after editing code
# you can start a container built from last week's source and get last week's
# behaviour, with nothing in the output telling you so. That bit us twice:
#
#   * a Flink image built before the unified-feed change subscribed to topics
#     named `binance.BTCUSDT.candles` and died on UnknownTopicOrPartitionException
#   * a frontend image built before the security headers were added served the
#     app happily, just without them
#
# Both looked like application bugs. Neither was.
#
# The fix is to make the image tag depend on the source. Change a file, and the
# tag changes; the image under the new tag does not exist yet, so Compose has to
# build it. Staleness stops being something you have to remember and becomes
# something that cannot happen.
#
# Usage:
#   scripts/image-tag.sh            # print the tag
#   TM_IMAGE_TAG=$(scripts/image-tag.sh) docker compose up -d
#
# Normally you don't call this directly — `make up` does it for you.

set -euo pipefail

cd "$(dirname "$0")/.."

# Everything that is COPYed into any of the three images, or that changes how
# they are built. Add to this list when you add a new build input, or the tag
# will not notice your change.
INPUTS=(
  # API image (Dockerfile) — also builds the UI bundle into itself
  Dockerfile
  requirements.txt
  requirements.lock
  alembic.ini
  app
  migrations

  # Flink image
  app/flink_jobs

  # Front-end image
  frontend/Dockerfile
  frontend/nginx.conf
  frontend/package.json
  frontend/package-lock.json
  frontend/index.html
  frontend/vite.config.ts
  frontend/tsconfig.json
  frontend/tsconfig.app.json
  frontend/tsconfig.node.json
  frontend/src
)

# Hash the file contents *and* their paths, so a rename or deletion changes the
# tag too. Sorted so the result does not depend on filesystem ordering.
#
# The excludes are things that never reach an image but change constantly —
# including them would churn the tag for no reason, and `dist` in particular is
# a build *output*, so hashing it would make the tag depend on itself.
hash_inputs() {
  for path in "${INPUTS[@]}"; do
    [ -e "$path" ] || continue
    find "$path" -type f \
      -not -path '*/node_modules/*' \
      -not -path '*/__pycache__/*' \
      -not -path '*/dist/*' \
      -not -path '*/.pytest_cache/*' \
      -not -name '*.pyc' \
      -not -name '.DS_Store' \
      -print0
  done | LC_ALL=C sort -z | xargs -0 sha256sum
}

if [ "${1:-}" = "--explain" ]; then
  echo "Files feeding the image tag:"
  hash_inputs | wc -l | sed 's/^/  files: /'
  echo "  tag:   $(hash_inputs | sha256sum | cut -c1-12)"
  exit 0
fi

hash_inputs | sha256sum | cut -c1-12
