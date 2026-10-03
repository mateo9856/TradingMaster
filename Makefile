# Thin wrapper around ./dev, for anyone who reaches for `make` out of habit.
# The real implementation lives in ./dev — a shell script, so it needs nothing
# installed beyond Docker. (`make` itself is not installed on every box; this
# project does not depend on it.)
#
#   make up    ==  ./dev up
#   ./dev help    lists every command

.DEFAULT_GOAL := help
.PHONY: help up infra down reset restart ps logs build rebuild stale \
        clean clean-images migrate psql archive verify test typecheck

help up infra down reset restart ps logs build rebuild stale clean \
clean-images migrate psql archive verify test typecheck:
	@./dev $@
