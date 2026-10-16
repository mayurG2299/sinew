import os

from dotenv import load_dotenv

load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


FALKORDB_HOST = env("FALKORDB_HOST", "localhost") or "localhost"
FALKORDB_PORT = int(env("FALKORDB_PORT", "6379") or "6379")
FALKORDB_USERNAME = env("FALKORDB_USERNAME") or None
FALKORDB_PASSWORD = env("FALKORDB_PASSWORD") or None
GEMINI_API_KEY = env("GEMINI_API_KEY")

TENANTS = ("northwind", "store2")
