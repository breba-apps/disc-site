import asyncio
import io
import logging
import os
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import chainlit as cl
import dns.resolver
from chainlit.auth import get_current_user, clear_auth_cookie
from chainlit.auth.cookie import clear_oauth_state_cookie
from chainlit.utils import mount_chainlit
from fastapi import FastAPI, File, Request, Depends, UploadFile
from fastapi import Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.staticfiles import StaticFiles

import breba_app.github_oauth as github_oauth
from breba_app.auth import change_password
from breba_app.config import init_db, load_env
from breba_app.github_controller import enforce_github_https, get_github_connection_status, handle_github_callback, \
    list_github_orgs, set_github_custom_domain
from breba_app.models.product import Product
from breba_app.models.user import User
from breba_app.orchestrator import load_state, state_exists
from breba_app.paths import app_path, templates
from breba_app.storage import read_all_files_in_memory, save_files
from breba_app.website import build_preview

logging.basicConfig(level=logging.INFO, )
logger = logging.getLogger(__name__)

load_env()

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


templates.env.globals['asset'] = asset_url

app.mount("/public",
          StaticFiles(directory=app_path / "public"),
          name="public")


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(app_path / "public" / "favicon.ico")


@app.get("/robots.txt")
async def robots():
    return FileResponse(app_path / "public" / "robots.txt")


@app.get("/sitemap.xml")
async def sitemap():
    return FileResponse(app_path / "public" / "sitemap.xml")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Home page route.
    If cookie "X-Chainlit-Session-id" is set, render app.html (builder UI).
    Otherwise render home.html (landing page).
    """
    session_cookie = request.cookies.get("X-Chainlit-Session-id")
    oauth_success = request.cookies.get("oauth_success")
    # Shortcut because oath is not being supported yet
    if oauth_success:
        response = templates.TemplateResponse("home.html", {"request": request, "login_success": True})
        response.delete_cookie("oauth_success")
        return response

    if session_cookie:
        return templates.TemplateResponse("app.html", {"request": request})
    else:
        return templates.TemplateResponse("home.html", {"request": request})


@app.get("/chainlit/login/callback")
async def chainlit_login_callback_passthrough(request: Request):
    response = RedirectResponse(url="/")
    response.set_cookie(
        "oauth_success",
        "1",
        max_age=5,
        httponly=True,
        samesite="lax",
    )
    clear_auth_cookie(request, response)
    clear_oauth_state_cookie(response)
    return response


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """
    Home page route. This just renders the HTML. All communication with the server is done through chianlit.
    """
    return templates.TemplateResponse("app.html", {"request": request})


@app.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    """
    Home page route. This just renders the HTML. All communication with the server is done through chianlit.
    """
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})


@app.post("/settings/account/password")
async def change_password_route(
        request: Request,
        current_user: Annotated[
            cl.User, Depends(get_current_user)
        ],
        current_password: str = Form(...),
        new_password: str = Form(...),
        confirm_password: str = Form(...),
):
    user_id = current_user.identifier

    if new_password != confirm_password:
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "error": "New passwords do not match.",
            },
            status_code=400
        )

    success = await change_password(user_id, current_password, new_password)

    if not success:
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "error": "Current password is incorrect.",
            },
            status_code=400
        )

    return RedirectResponse(url="/settings?success=1", status_code=303)


@app.get("/github/connect")
async def github_connect(
        current_user: Annotated[cl.User, Depends(get_current_user)],
):
    client_id = os.environ.get("GITHUB_CLIENT_ID", "")
    secret = os.environ.get("CHAINLIT_AUTH_SECRET", "")
    state = github_oauth.generate_state(current_user.identifier, secret)
    return RedirectResponse(url=github_oauth.build_github_auth_url(client_id, state))


@app.get("/github/callback", response_class=HTMLResponse)
async def github_callback(code: str = "", state: str = ""):
    result = await handle_github_callback(
        code=code,
        state=state,
        secret=os.environ.get("CHAINLIT_AUTH_SECRET", ""),
        client_id=os.environ.get("GITHUB_CLIENT_ID", ""),
        client_secret=os.environ.get("GITHUB_CLIENT_SECRET", ""),
    )
    if not result.success:
        return HTMLResponse(
            content=f"<html><body><p class='error'>{result.error}</p></body></html>",
            status_code=400,
        )
    return HTMLResponse(
        content="<html><head><script>window.close();</script></head><body><p class='success'>GitHub account connected. You may close this window.</p></body></html>",
    )


@app.get("/github/orgs")
async def github_orgs(
        current_user: Annotated[cl.User, Depends(get_current_user)],
):
    orgs = await list_github_orgs(current_user.identifier)
    if orgs is None:
        return {"orgs": [], "token_revoked": True}
    return {"orgs": orgs}


@app.post("/github/custom-domain")
async def github_set_custom_domain(
        request: Request,
        current_user: Annotated[cl.User, Depends(get_current_user)],
):
    body = await request.json()
    product_id = body.get("product_id", "")
    domain = body.get("domain", "").strip()
    if not domain:
        return {"success": False, "error": "Domain is required."}
    result = await set_github_custom_domain(current_user.identifier, product_id, domain)
    return {"success": result.success, "error": result.error}


GITHUB_PAGES_IPS = {"185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153"}


def _resolve_with(nameserver: str, domain: str) -> list[str]:
    resolver = dns.resolver.Resolver()
    resolver.nameservers = [nameserver]
    resolver.lifetime = 5.0
    try:
        return [rdata.address for rdata in resolver.resolve(domain, 'A')]
    except Exception:
        return []


@app.get("/github/dns-check")
async def github_dns_check(
        domain: str,
        current_user: Annotated[cl.User, Depends(get_current_user)],
        product_id: str = "",
):
    cloudflare_ips, google_ips = await asyncio.gather(
        asyncio.to_thread(_resolve_with, '1.1.1.1', domain),
        asyncio.to_thread(_resolve_with, '8.8.8.8', domain),
    )

    cloudflare_verified = any(ip in GITHUB_PAGES_IPS for ip in cloudflare_ips)
    google_verified = any(ip in GITHUB_PAGES_IPS for ip in google_ips)
    verified = cloudflare_verified and google_verified

    https_enforced = False
    if verified and product_id:
        result = await enforce_github_https(current_user.identifier, product_id)
        https_enforced = result.success

    return {
        "cloudflare": {"resolved": cloudflare_ips, "verified": cloudflare_verified},
        "google": {"resolved": google_ips, "verified": google_verified},
        "verified": verified,
        "https_enforced": https_enforced,
    }


@app.get("/github/status")
async def github_status(
        current_user: Annotated[cl.User, Depends(get_current_user)],
):
    result = await get_github_connection_status(current_user.identifier)
    return {"connected": result.connected, "github_username": result.github_username}


@app.get("/download")
async def download_project(
        current_user: Annotated[cl.User, Depends(get_current_user)],
):
    user_name = current_user.identifier
    user = await User.find_one(User.username == user_name)
    if not user:
        return HTMLResponse("User not found.", status_code=404)

    active_product = await Product.find_one(Product.user.id == user.id, Product.active == True)
    if not active_product:
        return HTMLResponse("No active product found.", status_code=404)

    filestore = await read_all_files_in_memory(user_name, active_product.product_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in filestore.list_files():
            zf.writestr(path, filestore.read_bytes(path))
    buf.seek(0)

    product_name = (active_product.name or "project").replace(" ", "-").lower()
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{product_name}.zip"'},
    )


@app.post("/upload")
async def upload_files(
        current_user: Annotated[cl.User, Depends(get_current_user)],
        files: list[UploadFile] = File(...),
        paths: list[str] = Form(...),
        product_id: str = Form(...),
):
    if len(files) != len(paths):
        return JSONResponse({"error": "files and paths counts do not match"}, status_code=400)

    user_name = current_user.identifier

    if not state_exists(user_name, product_id):
        # TODO: This can happen if we have multiple instances.
        #  The better way to do it ensure an instance lock is to re-use JSON-RPC over websockets
        return JSONResponse({"error": "User session is not found"}, status_code=404)

    state = load_state(user_name, product_id)

    for upload, rel_path in zip(files, paths):
        content = await upload.read()
        state.filestore.write_bytes(rel_path, content)

    files_to_save = list(state.filestore.snapshot().values())
    new_version, _ = await asyncio.gather(
        save_files(user_name, product_id, files_to_save),
        build_preview(product_id, state.filestore),
    )

    return JSONResponse({"version": new_version})


current_file_dir = Path(__file__).parent
mount_chainlit(app=app, target=str(current_file_dir / "my_cl_app.py"), path="/chainlit")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
