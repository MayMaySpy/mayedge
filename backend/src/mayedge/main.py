import copy
import logging

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from mayedge.api.app import app
from mayedge.config import settings

_LOG_DATE = "%H:%M:%S"
_LOG_FMT = "%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s"


def _log_config() -> dict:
    cfg = copy.deepcopy(LOGGING_CONFIG)
    cfg["formatters"]["default"]["fmt"] = "%(asctime)s.%(msecs)03d %(levelprefix)s %(message)s"
    cfg["formatters"]["default"]["datefmt"] = _LOG_DATE
    cfg["formatters"]["access"]["fmt"] = (
        '%(asctime)s.%(msecs)03d %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    )
    cfg["formatters"]["access"]["datefmt"] = _LOG_DATE
    return cfg


def _warn_if_public_bind(host: str) -> None:
    loopback = {"127.0.0.1", "localhost", "::1"}
    if host not in loopback:
        logging.getLogger(__name__).warning(
            "Binding to %s — no app auth; anyone who can reach this port can trade and kill. "
            "Use loopback publish + Tailscale Serve (see README).",
            host,
        )


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=_LOG_FMT,
        datefmt=_LOG_DATE,
        force=True,
    )
    _warn_if_public_bind(settings.bind_host)
    # Keep third-party chatter down; surface mayedge gateway/feed logs.
    logging.getLogger("mayedge").setLevel(logging.INFO)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.bind_port,
        reload=False,
        log_level="info",
        log_config=_log_config(),
    )


if __name__ == "__main__":
    run()
