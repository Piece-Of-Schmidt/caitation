import asyncio

import uvicorn

from backend.__main__ import selector_loop


def test_server_uses_the_selector_loop():
    # uvicorn resolves the loop string from python -m backend to this factory
    config = uvicorn.Config("backend.main:app", loop="backend.__main__:selector_loop")
    loop = config.get_loop_factory()()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
    assert selector_loop is not None
