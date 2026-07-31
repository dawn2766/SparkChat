"""Compatibility entry point for the Doubao realtime proxy."""

from server import main


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())