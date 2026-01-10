# Makefile

# Starts the containers in detached mode
up:
	docker compose up -d

# Stops and removes the containers
down:
	docker compose down

build:
	docker compose build

# Restarts all the services
restart:
	docker compose restart