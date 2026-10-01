"""Starts the Caitation server:  python -m backend  [--port 8000] [--reload]"""

import argparse
import asyncio

import uvicorn


def selector_loop() -> asyncio.AbstractEventLoop:
    # Not the proactor loop that is the default on Windows: when a client aborts a
    # connection while it is being accepted (WinError 64; happens with short timeouts on
    # a busy machine), the proactor loop closes the listening socket for good and
    # Caitation silently stops answering. The selector loop just drops that connection.
    return asyncio.SelectorEventLoop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m backend", description="Caitation-Server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="bei Codeänderungen neu starten")
    args = parser.parse_args()
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",  # local only; see backend/security.py
        port=args.port,
        reload=args.reload,
        loop="backend.__main__:selector_loop",
    )


if __name__ == "__main__":
    main()
