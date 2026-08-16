"""Development server entry point."""

import uvicorn


def run() -> None:
    """Run the Proto Virtual Lab API."""

    uvicorn.run(
        "proto_virtual_lab.api:create_app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        factory=True,
    )


if __name__ == "__main__":
    run()
