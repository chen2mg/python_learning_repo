# Makefile

# Starts the containers in detached mode and keeps the Mac awake
up:
	docker compose up -d
	$(MAKE) awake

# Stops and removes the containers, and lets the Mac sleep again
down:
	docker compose down
	$(MAKE) sleep

build:
	docker compose build

# Restarts all the services
restart:
	docker compose restart

# Prevent macOS from sleeping (detached, survives closing the terminal).
# -s: prevent system sleep on AC power. Display can still turn off.
awake:
	@pkill -f "caffeinate -s -i" 2>/dev/null || true
	@nohup caffeinate -s -i >/dev/null 2>&1 &
	@echo "caffeinate started: Mac will not sleep while containers run."

# Stop keeping the Mac awake (allow normal sleep again)
sleep:
	@pkill -f "caffeinate -s -i" 2>/dev/null || true
	@echo "caffeinate stopped: Mac can sleep normally now."