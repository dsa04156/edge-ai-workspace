"""Generate an experiment-only API key, never echo it or include it in results."""
import os
from pathlib import Path
import secrets
import sys

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write(secrets.token_hex(32) + "\n")
print("Private experiment API key created.")
