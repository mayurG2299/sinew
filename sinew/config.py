import os

from dotenv import load_dotenv

load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# No host set (or SINEW_LOCAL=1) means the local docker FalkorDB, which has no login.
_cloud = bool(env("FALKORDB_HOST")) and env("SINEW_LOCAL") != "1"
FALKORDB_HOST = env("FALKORDB_HOST") if _cloud else "localhost"
FALKORDB_PORT = int(env("FALKORDB_PORT") or "6379") if _cloud else 6379
FALKORDB_USERNAME = (env("FALKORDB_USERNAME") or None) if _cloud else None
FALKORDB_PASSWORD = (env("FALKORDB_PASSWORD") or None) if _cloud else None
GEMINI_API_KEY = env("GEMINI_API_KEY")

TENANTS = ("northwind", "store2")
