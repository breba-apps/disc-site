import os
import uvicorn


def main():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("breba_app.main:app", host=host, port=port, reload=False)


def dev():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("breba_app.main:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    main()
