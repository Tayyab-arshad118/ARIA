import logging

import uvicorn

from .config import Settings

if __name__ == "__main__":
    settings = Settings()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port,
                workers=1, access_log=False, log_level="warning", proxy_headers=False, server_header=False)
