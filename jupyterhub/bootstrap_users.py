import csv
import os
from pathlib import Path

import bcrypt
import jupyterhub.orm as hub_orm
from nativeauthenticator import orm as native_orm


DB_URL = os.environ.get("JUPYTERHUB_DB_URL", "sqlite:////srv/jupyterhub/data/jupyterhub.sqlite")
CREDENTIALS_FILE = os.environ.get(
    "JUPYTERHUB_CREDENTIALS_FILE", "/srv/jupyterhub/credentials/users.csv"
)
UPDATE_EXISTING = os.environ.get("JUPYTERHUB_UPDATE_EXISTING_PASSWORDS", "false").lower() == "true"


def _normalize_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _read_credentials(path: Path):
    if not path.exists():
        print(f"[bootstrap-users] credentials file not found at {path}; skipping")
        return []

    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(line for line in f if line.strip() and not line.strip().startswith("#"))
        required = {"username", "password"}
        if not reader.fieldnames or not required.issubset({h.strip().lower() for h in reader.fieldnames}):
            raise ValueError(
                "Credentials file must include header columns: username,password[,admin]"
            )

        for row in reader:
            username = (row.get("username") or "").strip().lower()
            password = (row.get("password") or "").strip()
            admin = _normalize_bool(row.get("admin", "false"))
            if not username or not password:
                continue
            rows.append({"username": username, "password": password, "admin": admin})
    return rows


def main():
    credentials = _read_credentials(Path(CREDENTIALS_FILE))
    if not credentials:
        print("[bootstrap-users] no credentials entries to process")
        return

    session_factory = hub_orm.new_session_factory(url=DB_URL)
    db = session_factory()

    # Ensure both JupyterHub and NativeAuthenticator tables exist.
    hub_orm.Base.metadata.create_all(db.bind)
    native_orm.Base.metadata.create_all(db.bind)

    created = 0
    updated = 0

    for item in credentials:
        username = item["username"]
        password = item["password"]
        admin = item["admin"]

        hub_user = hub_orm.User.find(db, username)
        if not hub_user:
            hub_user = hub_orm.User(name=username, admin=admin)
            db.add(hub_user)
            created += 1
        elif admin and not hub_user.admin:
            hub_user.admin = True
            updated += 1

        user_info = native_orm.UserInfo.find(db, username)
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        if not user_info:
            user_info = native_orm.UserInfo(
                username=username,
                password=hashed,
                is_authorized=True,
            )
            db.add(user_info)
            created += 1
        else:
            if UPDATE_EXISTING:
                user_info.password = hashed
                updated += 1
            if not user_info.is_authorized:
                user_info.is_authorized = True
                updated += 1

    db.commit()
    db.close()
    print(f"[bootstrap-users] done: created={created}, updated={updated}")


if __name__ == "__main__":
    main()
