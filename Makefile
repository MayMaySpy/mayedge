VPS ?= mayedge
REMOTE ?= /opt/mayedge
RSYNC_EXCL := deploy/rsync-exclude

.PHONY: help up down-local logs-local push-env deploy serve check logs down

help:
	@printf '%s\n' \
		'make up            local docker compose up --build' \
		'make down-local    local docker compose down' \
		'make logs-local    local compose logs' \
		'make push-env      rsync backend/.env → VPS (600)' \
		'make deploy        rsync tree, compose up --build, Tailscale Serve' \
		'make serve         Tailscale Serve → 127.0.0.1:14200' \
		'make check         loopback bind, health, Serve, Funnel off' \
		'make logs          VPS compose logs' \
		'make down          VPS compose down (volume kept)' \
		'VPS=$(VPS)  REMOTE=$(REMOTE)'

up:
	docker compose up -d --build

down-local:
	docker compose down

logs-local:
	docker compose logs -f --tail=200

push-env:
	test -f backend/.env || { echo 'missing backend/.env — cp backend/.env.example backend/.env' >&2; exit 1; }
	ssh $(VPS) 'mkdir -p $(REMOTE)/backend'
	rsync -az backend/.env $(VPS):$(REMOTE)/backend/.env
	ssh $(VPS) 'chmod 600 $(REMOTE)/backend/.env'

deploy:
	ssh $(VPS) 'mkdir -p $(REMOTE)'
	rsync -az --delete --exclude-from=$(RSYNC_EXCL) ./ $(VPS):$(REMOTE)/
	ssh $(VPS) 'test -f $(REMOTE)/backend/.env || { echo "run make push-env first" >&2; exit 1; }'
	ssh $(VPS) 'cd $(REMOTE) && docker compose up -d --build'
	$(MAKE) --no-print-directory serve
	@echo 'deployed. make check'

serve:
	ssh $(VPS) 'tailscale serve --bg http://127.0.0.1:14200'
	ssh $(VPS) 'tailscale serve status; echo; tailscale funnel status || true'

check:
	ssh $(VPS) "MAYEDGE_ROOT=$(REMOTE) bash -s" < deploy/check.sh

logs:
	ssh -t $(VPS) 'cd $(REMOTE) && docker compose logs -f --tail=200'

down:
	ssh $(VPS) 'cd $(REMOTE) && docker compose down'
