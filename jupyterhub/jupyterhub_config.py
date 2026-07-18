import os
from pathlib import Path

# If your workspace path changes, set APP_HOST_DIR in .env or compose env.
APP_HOST_DIR = os.environ.get("APP_HOST_DIR", "/home/eg2577/repo/jupyterlab/app")
APP_SCAN_DIR = os.environ.get("APP_SCAN_DIR", "/srv/app")
ADMIN_USERS = {
    u.strip().lower()
    for u in os.environ.get("JUPYTERHUB_ADMIN_USERS", "").split(",")
    if u.strip()
}
EXTRA_ALLOWED_USERS = {
    u.strip().lower()
    for u in os.environ.get("JUPYTERHUB_ALLOWED_USERS", "").split(",")
    if u.strip()
}

c = get_config()  # noqa: F821

c.JupyterHub.bind_url = "http://:8000"
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.admin_access = True
c.JupyterHub.db_url = "sqlite:////srv/jupyterhub/data/jupyterhub.sqlite"
c.JupyterHub.template_vars = {
    "announcement": '<a href="/hub/change-password">Change Password</a>',
}

c.JupyterHub.authenticator_class = "nativeauthenticator.NativeAuthenticator"

# Build allowed users from existing folders (one folder per person) and env overrides.
_folder_users = set()
scan_root = Path(APP_SCAN_DIR)
if scan_root.exists():
    _folder_users = {p.name.lower() for p in scan_root.iterdir() if p.is_dir()}

ALL_ALLOWED_USERS = _folder_users | EXTRA_ALLOWED_USERS | ADMIN_USERS

c.Authenticator.allowed_users = ALL_ALLOWED_USERS
c.Authenticator.admin_users = ADMIN_USERS

# Allow all authenticated users in this deployment to open the quiz service.
c.JupyterHub.load_roles = [
    {
        "name": "quiz-access",
        "description": "Allow users to access the quiz service UI",
        "scopes": ["access:services!service=quiz"],
        "users": sorted(ALL_ALLOWED_USERS),
    }
]

# Disable self-signup. Accounts are provisioned by admin/bootstrap only.
c.NativeAuthenticator.open_signup = False
c.NativeAuthenticator.minimum_password_length = 8
c.NativeAuthenticator.ask_email_on_signup = False

c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.DockerSpawner.image = "jupyter/base-notebook:latest"
c.DockerSpawner.network_name = "jupyterhub_net"
c.DockerSpawner.remove = True
c.DockerSpawner.notebook_dir = "/home/jovyan/work"
c.Spawner.default_url = "/lab"


def _resolve_user_folder(username: str) -> str:
    """Map lowercase login names to existing folder names case-insensitively."""
    scan_root = Path(APP_SCAN_DIR)
    if scan_root.exists():
        for child in scan_root.iterdir():
            if child.is_dir() and child.name.lower() == username.lower():
                return child.name
    return username


def _pre_spawn_hook(spawner):
    folder_name = _resolve_user_folder(spawner.user.name)
    host_user_dir = str(Path(APP_HOST_DIR) / folder_name)
    os.makedirs(host_user_dir, exist_ok=True)
    spawner.volumes = {
        host_user_dir: {"bind": "/home/jovyan/work", "mode": "rw"},
    }


c.Spawner.pre_spawn_hook = _pre_spawn_hook

# ---------------------------------------------------------------------------
# Quiz Service
# ---------------------------------------------------------------------------
# JupyterHub will:
#   • spawn the process, injecting JUPYTERHUB_SERVICE_* env vars automatically
#   • proxy  /hub/services/quiz/  →  http://127.0.0.1:10101
#   • handle OAuth so the service can call get_current_user()
#
# The service link appears in the Hub top-navigation under "Services".
# ---------------------------------------------------------------------------
c.JupyterHub.services = [
    {
        "name": "quiz",
        # Where JupyterHub will proxy to (must match what quiz_service.py listens on)
        "url": "http://127.0.0.1:10101",
        # JupyterHub starts this command inside the hub container
        "command": ["python3", "/srv/jupyterhub/quiz_service.py"],
        # Skip the OAuth "do you allow this application?" confirmation page
        "oauth_no_confirm": True,
        # Extra env vars forwarded to the service process
        "environment": {
            "QUIZ_DATA_DIR":    "/srv/jupyterhub/quiz_data",
            "QUIZ_RESULT_DIR":  "/srv/jupyterhub/quiz_result",
            "QUIZ_ADMIN_USER":  "eg2577,eric",
            "QUIZ_PASS_THRESHOLD": "0.8",
        },
        # Show this service as a link in the Hub navbar (JupyterHub 2+)
        "display": True,
    }
]
