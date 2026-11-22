"""Run the service: `python -m aegis.api`.

A convenience wrapper so the app starts the same way in development and in a
container, without anyone having to remember the uvicorn incantation. PORT is
read from the environment because that is how every host assigns one.
"""
import os


def main():
    import uvicorn
    uvicorn.run(
        "aegis.api.app:app",
        host=os.environ.get("AEGIS_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("AEGIS_RELOAD", "").lower() in ("1", "true", "yes"),
        log_level=os.environ.get("AEGIS_LOG_LEVEL", "info"),
        proxy_headers=True,             # correct scheme/host behind a platform proxy
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
