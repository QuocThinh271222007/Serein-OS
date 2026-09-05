"""Allows ``python -m serein`` as a development-time invocation."""

from serein.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
