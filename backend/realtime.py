"""Executable entry point for the realtime speech proxy."""

import asyncio

from .realtime_server import main


if __name__ == "__main__":
    asyncio.run(main())
