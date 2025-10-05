import logging
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

from chainlit.context import init_ws_context
from chainlit.session import WebsocketSession
from chainlit.utils import mount_chainlit
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from breba_app.generator_agent.agent import agent
from breba_app.storage import read_image_from_private
from breba_app.config import init_db

logging.basicConfig(level=logging.INFO, )
logger = logging.getLogger(__name__)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))


@asynccontextmanager
async def lifespan(app):
    await init_db()
    pat = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    await agent.ensure_initialized(pat)
    yield
    await agent.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app_path = Path(__file__).parent

import time

# Compute static asset version based on max mtime of public files on startup
public_dir = app_path / "public"
if public_dir.exists():
    mtimes = [f.stat().st_mtime for f in public_dir.rglob('*') if f.is_file()]
    ASSET_VERSION = str(int(max(mtimes))) if mtimes else "1"
else:
    ASSET_VERSION = "1"

def asset_url(filename):
    base = f"/public/{filename}"
    return f"{base}?v={ASSET_VERSION}"

templates = Jinja2Templates(directory=app_path / "templates")
templates.env.globals['asset'] = asset_url

app.mount("/public",
          StaticFiles(directory=app_path / "public"),
          name="public")


@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse(url="/public/favicon.ico")


@app.api_route("/images/{session_id}/{file_path:path}", methods=["GET", "HEAD"])
async def custom_static_handler(session_id: str, file_path: str, request: Request):
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session ID")

    ws_session = WebsocketSession.get_by_id(session_id=session_id)
    init_ws_context(ws_session)

    user_name: str = ws_session.user.identifier
    image_bytes, metadata = read_image_from_private(user_name=user_name, session_id=session_id, image_name=file_path)

    if not image_bytes:
        raise HTTPException(status_code=404, detail="File not found")

    # Guess MIME type from filename
    media_type, _ = mimetypes.guess_type(file_path)
    media_type = media_type or "application/octet-stream"

    headers = {
        "Content-Type": media_type,
        "Content-Length": str(len(image_bytes)),
    }

    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)

    return Response(content=image_bytes, media_type=media_type, headers=headers)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Home page route.
    If cookie "X-Chainlit-Session-id" is set, render home.html
    otherwise render base.html
    """
    session_cookie = request.cookies.get("X-Chainlit-Session-id")

    if session_cookie:
        # Cookie missing → render base.html
        return templates.TemplateResponse("base.html", {"request": request})
    else:
        # Cookie exists → render home.html
        return templates.TemplateResponse("home.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """
    Home page route. This just renders the HTML. All communication with the server is done through chianlit.
    """
    return templates.TemplateResponse("base.html", {"request": request})


@app.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    """
    Home page route. This just renders the HTML. All communication with the server is done through chianlit.
    """
    return templates.TemplateResponse("home.html", {"request": request})


current_file_dir = Path(__file__).parent
mount_chainlit(app=app, target=str(current_file_dir / "my_cl_app.py"), path="/chainlit")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
