# Python & AI Learning Platform

A self-hosted [JupyterHub](https://jupyter.org/hub) server for teaching kids Python and AI concepts through structured, hands-on notebook lessons. Each student gets an isolated JupyterLab environment with their own workspace, progress tracking, and chapter quizzes.

---

## Features

- **Multi-user JupyterHub** — each student logs in and lands in their own private workspace
- **Structured curriculum** — 3 stages × up to 10 chapters per stage, delivered as Jupyter notebooks
- **Built-in quiz system** — chapter quizzes with automatic scoring and admin result viewer
- **User bootstrapping** — accounts and passwords are provisioned from a CSV file at startup
- **Cloudflare Tunnel** — optional secure public access without opening firewall ports
- **Docker Compose** — single-command setup and teardown

---

## Project Structure

```
.
├── app/                        # Student workspaces (one folder per student)
│   └── <StudentName>/
│       ├── stage1/             # Chapters 01–10
│       ├── stage2/             # Chapters 01–10
│       └── stage3/             # Chapters 01–05
├── jupyterhub/
│   ├── Dockerfile              # JupyterHub image
│   ├── jupyterhub_config.py    # Hub configuration
│   ├── bootstrap_users.py      # Creates accounts from credentials CSV on startup
│   ├── quiz_service.py         # Quiz web service (scoring + admin viewer)
│   ├── credentials/
│   │   ├── users.csv.example   # Template — copy to users.csv and set passwords
│   │   └── users.csv           # Live credentials (gitignored)
│   ├── quiz_data/              # Quiz question JSON files (s<stage>c<chapter>.json)
│   └── quiz_result/            # Per-student attempt history (JSON)
├── jupyterhub-data/            # Persistent SQLite database (gitignored)
├── docker-compose.yml
└── makefile
```

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/) installed
- (Optional) A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) token for public access

---

## Setup

### 1. Create the credentials file

```bash
cp jupyterhub/credentials/users.csv.example jupyterhub/credentials/users.csv
```

Edit `users.csv` and set a strong password for each student. The `admin` column accepts `true` or `false`.

```csv
username,password,admin
alice,StrongPassword1!,false
bob,StrongPassword2!,false
teacher,TeacherPassword!,true
```

> **Note:** `users.csv` is gitignored. Never commit passwords to version control.

### 2. Create a `.env` file

```bash
cat > .env << 'EOF'
# Absolute path to the app/ directory on the Docker host.
# JupyterHub mounts each student's subfolder into their container.
APP_HOST_DIR=/absolute/path/to/repo/app

# Comma-separated admin usernames (must also appear in users.csv)
JUPYTERHUB_ADMIN_USERS=teacher

# Additional allowed users not inferred from app/ folder names (optional)
JUPYTERHUB_ALLOWED_USERS=

# Set to "true" to overwrite existing passwords on next startup
JUPYTERHUB_UPDATE_EXISTING_PASSWORDS=false

# Cloudflare Tunnel token (leave blank to disable)
CLOUDFLARED_TOKEN=
EOF
```

### 3. Add student notebook folders

Create a subfolder under `app/` for each student. The folder name must match the username in `users.csv` (case-insensitive). Copy the stage/chapter notebooks into each student's folder.

```bash
mkdir -p app/Alice/stage1 app/Alice/stage2 app/Alice/stage3
# Copy notebooks...
```

---

## Running the Server

```bash
# Build the JupyterHub image
make build

# Start all services in the background
make up

# Stop and remove all containers
make down

# Restart all services
make restart
```

The Hub is accessible at **http://localhost** (port 80) by default. If a Cloudflare Tunnel token is configured, it is also reachable at the tunnel's public URL.

---

## User Management

Accounts are created automatically at startup by `bootstrap_users.py`, which reads `credentials/users.csv`. To add or update users:

1. Edit `credentials/users.csv`.
2. Set `JUPYTERHUB_UPDATE_EXISTING_PASSWORDS=true` in `.env` if you need to reset an existing password.
3. Run `make restart`.

Students can change their own password after logging in via the **Change Password** link shown on the Hub home page.

---

## Quiz System

Quizzes are served at `/hub/services/quiz/` and are keyed by stage and chapter (e.g., `s1c3.json` = Stage 1, Chapter 3).

| URL | Description |
|-----|-------------|
| `/hub/services/quiz/` | Take a quiz |
| `/hub/services/quiz/results` | Admin result viewer (admin users only) |

Quiz questions are stored as JSON files in `jupyterhub/quiz_data/`. Results are persisted per-student in `jupyterhub/quiz_result/`. The default pass threshold is **80%**.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_HOST_DIR` | Yes | — | Absolute path to `app/` on the Docker host |
| `JUPYTERHUB_ADMIN_USERS` | No | — | Comma-separated admin usernames |
| `JUPYTERHUB_ALLOWED_USERS` | No | — | Extra allowed users beyond those with folders |
| `JUPYTERHUB_UPDATE_EXISTING_PASSWORDS` | No | `false` | Overwrite passwords on startup |
| `CLOUDFLARED_TOKEN` | No | — | Cloudflare Tunnel token |
