"""Usage:
    python app.py --model TabbyML/StarCoder-1B --device metal
"""

import socket
import time
import asyncio
import argparse
import uvicorn
import subprocess
from asgi_proxy import asgi_proxy

class TabbyLauncher(object):
    def __init__(self, args: list[str], host: str, port: int):
        self.proc = None
        self.args = args
        self.host = host
        self.port = port

    def start(self):
        print("Starting tabby process...")
        self.proc = subprocess.Popen(
            [
                "tabby",
                "serve",
            ]
            + self.args
            + [
                "--port",
                str(self.port),
            ],
        )

        while not self._server_ready():
            time.sleep(1.0)
        return self

    def _server_ready(self):
        # Poll until webserver accepts connections before running inputs.
        try:
            socket.create_connection((self.host, self.port), timeout=1).close()
            print("Tabby server ready!")
            return True
        except (socket.timeout, ConnectionRefusedError):
            # Check if launcher webserving process has exited.
            # If so, a connection can never be made.
            retcode = self.proc.poll()
            if retcode is not None:
                raise RuntimeError(f"launcher exited unexpectedly with code {retcode}")
            return False

    @property
    def is_running(self):
        return self.proc is not None

    def stop(self):
        if self.proc is None:
            return

        self.proc.terminate()
        self.proc = None
        print("Tabby process stopped.")


class Timer:
    def __init__(self, timeout, callback):
        self._timeout = timeout
        self._callback = callback
        self._task = asyncio.ensure_future(self._job())

    async def _job(self):
        await asyncio.sleep(self._timeout)
        self._callback()

    def cancel(self):
        self._task.cancel()


def supervisor(serve_args, timeout, host, port):
    launcher = TabbyLauncher(serve_args, host, port)
    proxy = asgi_proxy(f"http://{host}:{port}")
    timer = None

    async def callback(scope, receive, send):
        nonlocal timer
        
        # Start only on http request.
        assert scope["type"] == "http"
    
        if not launcher.is_running:
            launcher.start()
        elif timer is not None:
            timer = timer.cancel()

        timer = Timer(timeout, launcher.stop)
        return await proxy(scope, receive, send)

    return callback


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start a tabby supervisor")
    parser.add_argument(
        "-p", "--port", type=int, default=9080, help="Port to use (default: 9080)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--timeout", default=300, help="Idle time after which the server is shut down. (default: 300)"
    )
    parser.add_argument(
        "--tabbyport", type=int, default=9081, help="Port to use for tabby server (default: 9081)"
    )
    parser.add_argument(
        "--tabbyhost", default="127.0.0.1", help="Host to bind tabby server to (default: 127.0.0.1)"
    )

    args, serve_args = parser.parse_known_args()

    app = supervisor(serve_args, args.timeout, args.tabbyhost, args.tabbyport)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
