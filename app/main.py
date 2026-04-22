from pathlib import Path
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
import urllib.parse

import json

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import configure_logging
from app.db.migrations import run_migrations
from app.db.session import engine, get_db
from app.models import AppSetting, Article, Cluster, ServiceState, SocialItem, Source, User
from app.services.auth import authenticate_user, hash_password, manager, require_admin, require_user
from app.services.backup_restore import BackupValidationError, backup_bytes, restore_backup
from app.services.bootstrap import bootstrap_data
from app.services.llm import LLMService
from app.services.ingestion import _sync_sources_from_miniflux
from app.services.meili import MeiliService
from app.services.miniflux_client import MinifluxClient
from app.services.ranking import looks_us_focused
from app.services.social_context import split_social_sections
from app.tasks.celery_app import celery_app
from app.tasks.jobs import retry_miniflux_bootstrap_task, run_pipeline_task

configure_logging()
app = FastAPI(title="Yesterday's Scoop")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _relative_minutes(dt):
    if not dt:
        return "just now"
    delta_mins = max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 60))
    if delta_mins < 1:
        return "just now"
    if delta_mins == 1:
        return "1 minute ago"
    if delta_mins < 60:
        return f"{delta_mins} minutes ago"
    hours = delta_mins // 60
    if hours == 1:
        return "1 hour ago"
    return f"{hours} hours ago"


templates.env.filters["relative_minutes"] = _relative_minutes


@app.on_event("startup")
def startup() -> None:
    try:
        run_migrations()
    except Exception as exc:
        logger.exception("Startup migration step failed: %s", exc)
        raise

    try:
        with Session(engine) as db:
            bootstrap_data(db)
    except Exception as exc:
        logger.exception("Startup bootstrap step failed: %s", exc)
        raise

    meili = MeiliService()
    try:
        meili.bootstrap_indexes()
    except Exception as exc:
        logger.warning("Meilisearch bootstrap failed on startup; scheduled retries will continue: %s", exc)


@app.get("/health")
def health() -> dict:
    status = {
        "status": "ok",
        "database": False,
        "miniflux": False,
        "miniflux_bootstrapped": False,
        "miniflux_last_attempt_at": None,
        "miniflux_retry_count": 0,
        "scheduler_healthy": False,
        "worker_healthy": False,
        "last_pipeline_started_at": None,
        "last_pipeline_finished_at": None,
        "last_pipeline_success": None,
        "last_pipeline_stage": None,
        "last_pipeline_error": None,
        "meilisearch": False,
        "ollama": False,
    }

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["database"] = True
    except Exception:
        status["database"] = False

    try:
        status["miniflux"] = MinifluxClient().health()
    except Exception:
        status["miniflux"] = False

    try:
        with Session(engine) as db:
            settings = db.scalar(select(AppSetting).limit(1))
            status["miniflux_bootstrapped"] = bool(settings and settings.miniflux_bootstrap_completed)
            if settings:
                status["miniflux_last_attempt_at"] = settings.miniflux_last_attempt_at.isoformat() if settings.miniflux_last_attempt_at else None
                status["miniflux_retry_count"] = settings.miniflux_retry_count
            svc_state = db.scalar(select(ServiceState).where(ServiceState.id == 1))
            if svc_state:
                status["last_pipeline_started_at"] = svc_state.last_pipeline_started_at.isoformat() if svc_state.last_pipeline_started_at else None
                status["last_pipeline_finished_at"] = svc_state.last_pipeline_finished_at.isoformat() if svc_state.last_pipeline_finished_at else None
                status["last_pipeline_success"] = svc_state.last_pipeline_success
                status["last_pipeline_stage"] = svc_state.last_pipeline_stage
                status["last_pipeline_error"] = svc_state.last_pipeline_error
                if svc_state.scheduler_last_tick_at:
                    age = (datetime.now(timezone.utc) - svc_state.scheduler_last_tick_at).total_seconds()
                    status["scheduler_healthy"] = age <= 180
                if svc_state.worker_last_heartbeat_at:
                    worker_age = (datetime.now(timezone.utc) - svc_state.worker_last_heartbeat_at).total_seconds()
                    status["worker_healthy"] = worker_age <= 180
    except Exception:
        status["miniflux_bootstrapped"] = False

    try:
        status["meilisearch"] = MeiliService().health()
    except Exception:
        status["meilisearch"] = False

    try:
        status["ollama"] = LLMService().ollama_health()
    except Exception:
        status["ollama"] = False

    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        ping_result = inspector.ping() or {}
        status["worker_healthy"] = status["worker_healthy"] and bool(ping_result)
    except Exception:
        status["worker_healthy"] = False

    if not all([status["database"], status["miniflux"], status["miniflux_bootstrapped"], status["meilisearch"], status["ollama"], status["scheduler_healthy"], status["worker_healthy"]]):
        status["status"] = "degraded"
    return status


def _dashboard_metrics(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)

    articles_1h = int(db.scalar(select(func.count(Article.id)).where(Article.ingested_at >= one_hour_ago)) or 0)
    articles_24h = int(db.scalar(select(func.count(Article.id)).where(Article.ingested_at >= day_ago)) or 0)
    clusters_1h = int(db.scalar(select(func.count(Cluster.id)).where(Cluster.updated_at >= one_hour_ago)) or 0)
    clusters_24h = int(db.scalar(select(func.count(Cluster.id)).where(Cluster.updated_at >= day_ago)) or 0)
    return {
        "articles_1h": articles_1h,
        "articles_24h": articles_24h,
        "clusters_1h": clusters_1h,
        "clusters_24h": clusters_24h,
    }



def _safe_next_url(next_url: str | None) -> str:
    candidate = (next_url or "").strip()
    if not candidate:
        return "/"

    parts = urllib.parse.urlsplit(candidate)
    if parts.scheme or parts.netloc:
        return "/"
    if not parts.path.startswith("/") or parts.path.startswith("//"):
        return "/"

    return urllib.parse.urlunsplit(("", "", parts.path, parts.query, ""))


@app.exception_handler(HTTPException)
async def app_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        accept_header = (request.headers.get("accept") or "").lower()
        wants_html = "text/html" in accept_header
        if wants_html and request.url.path not in {"/login", "/logout"}:
            next_path = request.url.path
            if request.url.query:
                next_path = f"{next_path}?{request.url.query}"
            safe_next = _safe_next_url(next_path)
            return RedirectResponse(f"/login?next={quote_plus(safe_next)}", status_code=303)
    return await http_exception_handler(request, exc)



def _is_setup_completed(db: Session) -> bool:
    settings = db.scalar(select(AppSetting).limit(1))
    return bool(settings and settings.setup_completed)




@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if not _is_setup_completed(db):
        return RedirectResponse("/setup/1", status_code=303)
    next_url = _safe_next_url(request.query_params.get("next"))
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "title": "Sign in",
            "error": request.query_params.get("error"),
            "next": next_url,
            "current_user": None,
            "bootstrap_pending": False,
        },
    )


@app.post("/login")
def login_submit(
    db: Session = Depends(get_db),
    username: str = Form(""),
    password: str = Form(""),
    next_url: str = Form("/"),
):
    safe_next_url = _safe_next_url(next_url)
    user = authenticate_user(db, username=username.strip(), password=password)
    if not user:
        return RedirectResponse(
            f"/login?error=Invalid+username+or+password&next={quote_plus(safe_next_url)}",
            status_code=303,
        )

    token = manager.create_access_token(data={"sub": user.username})
    response = RedirectResponse(safe_next_url, status_code=303)
    manager.set_cookie(response, token)
    return response


@app.post("/logout")
def logout_submit():
    response = RedirectResponse("/login?ok=Logged+out", status_code=303)
    response.delete_cookie(manager.cookie_name)
    return response




@app.get("/", response_class=HTMLResponse)
def homepage(request: Request, db: Session = Depends(get_db), current_user=Depends(require_user)):
    if not _is_setup_completed(db):
        return RedirectResponse("/setup/1", status_code=303)
    settings = db.scalar(select(AppSetting).limit(1))
    region = ((settings.region if settings else "") or "").strip().lower()
    sections = _homepage_sections(db, region)
    hero = sections["top_story_now"][0] if sections["top_story_now"] else None
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "hero": hero,
            "sections": sections,
            "title": "Daily Briefing",
            "current_user": current_user,
            "bootstrap_pending": not bool(settings and settings.miniflux_bootstrap_completed),
        },
    )


def _homepage_sections(db: Session, region: str) -> dict[str, list[Cluster]]:
    base = db.scalars(select(Cluster).order_by(desc(Cluster.score), desc(Cluster.updated_at)).limit(120)).all()

    def _fresh(items: list[Cluster]) -> list[Cluster]:
        return [c for c in items if (c.cluster_state or "") != "archived"]

    top_story_now = _fresh(base)[:1]
    developing_near_you = [
        c
        for c in _fresh(base)
        if c.local_relevance_score >= 0.25 and (c.cluster_state in {"emerging", "developing", "major"})
    ][:6]
    major_us = [c for c in _fresh(base) if c.cluster_state in {"major", "developing"} and looks_us_focused(c)][:6]
    major_world = [c for c in _fresh(base) if c.cluster_state in {"major", "developing"} and not looks_us_focused(c)][:6]
    fast_moving = sorted(_fresh(base), key=lambda c: (c.velocity_score, c.score), reverse=True)[:6]
    recently_updated = sorted(_fresh(base), key=lambda c: c.updated_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:6]

    if region and not developing_near_you:
        developing_near_you = [c for c in _fresh(base) if c.cluster_state in {"developing", "major"}][:6]

    return {
        "top_story_now": top_story_now,
        "developing_near_you": developing_near_you,
        "major_us": major_us,
        "major_world": major_world,
        "fast_moving": fast_moving,
        "recently_updated": recently_updated,
    }


@app.get("/clusters/{slug}", response_class=HTMLResponse)
def cluster_detail(slug: str, request: Request, db: Session = Depends(get_db), current_user=Depends(require_user)):
    if not _is_setup_completed(db):
        return RedirectResponse("/setup/1", status_code=303)
    cluster = db.scalar(select(Cluster).where(Cluster.slug == slug))
    if not cluster:
        return RedirectResponse("/")
    articles = db.scalars(select(Article).where(Article.cluster_id == cluster.id).order_by(desc(Article.published_at))).all()
    social_items = db.scalars(
        select(SocialItem).where(SocialItem.cluster_id == cluster.id).order_by(desc(SocialItem.created_at)).limit(20)
    ).all()
    official_responses, public_reaction = split_social_sections(social_items)
    settings = db.scalar(select(AppSetting).limit(1))
    return templates.TemplateResponse(
        "cluster_detail.html",
        {
            "request": request,
            "cluster": cluster,
            "articles": articles,
            "official_responses": official_responses,
            "public_reaction": public_reaction,
            "title": cluster.title,
            "current_user": current_user,
            "bootstrap_pending": not bool(settings and settings.miniflux_bootstrap_completed),
        },
    )


@app.get("/search", response_class=HTMLResponse)
def search(q: str = "", request: Request = None, db: Session = Depends(get_db), current_user=Depends(require_user)):
    if not _is_setup_completed(db):
        return RedirectResponse("/setup/1", status_code=303)
    meili = MeiliService()
    results = {"clusters": [], "articles": []}
    settings = db.scalar(select(AppSetting).limit(1))
    if q:
        try:
            results = meili.search(q)
        except Exception as exc:
            logger.warning("Search failed due to Meilisearch error: %s", exc)
            results = {"clusters": [], "articles": []}
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "results": results,
            "q": q,
            "title": "Search",
            "current_user": current_user,
            "bootstrap_pending": not bool(settings and settings.miniflux_bootstrap_completed),
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_admin)):
    settings = db.scalar(select(AppSetting).limit(1))
    return templates.TemplateResponse("settings.html", {"request": request, "settings": settings, "title": "Settings", "current_user": current_user, "bootstrap_pending": not bool(settings and settings.miniflux_bootstrap_completed)})


@app.get("/ai", response_class=HTMLResponse)
def ai_config_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_admin)):
    settings = db.scalar(select(AppSetting).limit(1))
    llm = LLMService()
    models = llm.list_ollama_models()
    ollama_connected = llm.ollama_health()
    return templates.TemplateResponse(
        "ai_config.html",
        {
            "request": request,
            "title": "AI Configuration",
            "current_user": current_user,
            "bootstrap_pending": not bool(settings and settings.miniflux_bootstrap_completed),
            "settings": settings,
            "models": models,
            "ollama_connected": ollama_connected,
            "summary_model_ok": bool(settings and settings.ollama_chat_model and settings.ollama_chat_model in models),
            "embed_model_ok": bool(settings and settings.ollama_embed_model and settings.ollama_embed_model in models),
            "error": request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
        },
    )


@app.post("/ai/save")
def ai_config_save(
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
    llm_provider: str = Form("ollama"),
    enable_ai_summarization: bool = Form(False),
    ollama_base_url: str = Form(""),
    ollama_chat_model: str = Form(""),
    ollama_embed_model: str = Form(""),
    openai_api_key: str = Form(""),
    openai_model: str = Form(""),
    openai_fallback_enabled: bool = Form(False),
):
    settings = db.scalar(select(AppSetting).limit(1))
    if not settings:
        return RedirectResponse("/ai?error=Settings+missing", status_code=303)
    settings.llm_provider = llm_provider if llm_provider in {"ollama", "openai"} else "ollama"
    settings.enable_ai_summarization = enable_ai_summarization
    settings.ollama_base_url = ollama_base_url.strip() or settings.ollama_base_url
    settings.ollama_chat_model = ollama_chat_model.strip() or settings.ollama_chat_model
    settings.ollama_embed_model = ollama_embed_model.strip() or settings.ollama_embed_model
    settings.openai_api_key = openai_api_key.strip() or settings.openai_api_key
    settings.openai_model = openai_model.strip() or settings.openai_model
    settings.openai_fallback_enabled = openai_fallback_enabled
    db.commit()
    return RedirectResponse("/ai?ok=AI+configuration+saved", status_code=303)


@app.post("/ai/pull-model")
def ai_pull_model(model_name: str = Form(...), _: object = Depends(require_admin)):
    try:
        LLMService().pull_ollama_model(model_name.strip())
        return RedirectResponse("/ai?ok=Model+pull+started%2Fcompleted", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/ai?error={str(exc)}", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db), current_user=Depends(require_admin)):
    settings = db.scalar(select(AppSetting).limit(1))
    svc_state = db.scalar(select(ServiceState).where(ServiceState.id == 1))
    health_status = health()
    metrics = _dashboard_metrics(db)
    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "title": "Admin Dashboard",
            "current_user": current_user,
            "bootstrap_pending": not bool(settings and settings.miniflux_bootstrap_completed),
            "health": health_status,
            "settings": settings,
            "svc_state": svc_state,
            "metrics": metrics,
        },
    )


@app.post("/settings")
def update_settings(
    enable_ai_summarization: bool = Form(False),
    enable_social_context: bool = Form(False),
    enable_reddit_context: bool = Form(False),
    enable_x_context: bool = Form(False),
    social_max_items: int = Form(8),
    x_api_bearer_token: str = Form(""),
    poll_interval_minutes: int = Form(15),
    region: str = Form("global"),
    topics: str = Form("world,technology"),
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    settings = db.scalar(select(AppSetting).limit(1))
    settings.enable_ai_summarization = enable_ai_summarization
    settings.enable_social_context = enable_social_context
    settings.enable_reddit_context = enable_reddit_context
    settings.enable_x_context = enable_x_context
    settings.social_max_items = max(1, min(social_max_items, 30))
    settings.x_api_bearer_token = x_api_bearer_token.strip() or None
    settings.poll_interval_minutes = poll_interval_minutes
    settings.region = region
    settings.topics = [t.strip() for t in topics.split(",") if t.strip()]
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.post("/pipeline/run")
def trigger_pipeline(_: object = Depends(require_admin)):
    task = run_pipeline_task.delay()
    return {"queued": True, "task_id": task.id}


@app.post("/admin/run-pipeline")
def admin_run_pipeline(_: object = Depends(require_admin)):
    run_pipeline_task.delay()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/retry-bootstrap")
def admin_retry_bootstrap(_: object = Depends(require_admin)):
    retry_miniflux_bootstrap_task.delay()
    return RedirectResponse("/admin", status_code=303)


@app.get("/backups", response_class=HTMLResponse)
def backups_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_admin)):
    settings = db.scalar(select(AppSetting).limit(1))
    return templates.TemplateResponse(
        "backups.html",
        {
            "request": request,
            "title": "Backups",
            "current_user": current_user,
            "bootstrap_pending": not bool(settings and settings.miniflux_bootstrap_completed),
            "error": request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
        },
    )


@app.post("/backups/export")
def export_backup_file(
    include_articles: bool = Form(False),
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    content = backup_bytes(db, include_articles=include_articles)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename=\"yesterdays-scoop-backup-{stamp}.json\"'},
    )


@app.post("/backups/restore")
async def restore_backup_file(
    backup_file: UploadFile = File(...),
    confirm_overwrite: bool = Form(False),
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    try:
        payload = json.loads((await backup_file.read()).decode("utf-8"))
        counts = restore_backup(db, payload, confirm_overwrite=confirm_overwrite)
        summary = ", ".join(f"{k}={v}" for k, v in counts.items())
        return RedirectResponse(f"/backups?ok=Restore+completed:+{summary}", status_code=303)
    except BackupValidationError as exc:
        return RedirectResponse(f"/backups?error={str(exc)}", status_code=303)
    except Exception as exc:
        logger.exception("Backup restore failed: %s", exc)
        return RedirectResponse("/backups?error=Restore+failed.+Check+logs.", status_code=303)


@app.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_admin)):
    feeds = []
    error = None
    try:
        feeds = MinifluxClient().list_feeds()
        _sync_sources_from_miniflux(db, feeds)
    except Exception as exc:
        error = f"Could not load feeds from Miniflux: {exc}"

    source_rows = db.scalars(select(Source).order_by(Source.source_tier.asc(), Source.name.asc())).all()
    source_by_url = {s.feed_url: s for s in source_rows}
    settings = db.scalar(select(AppSetting).limit(1))
    return templates.TemplateResponse(
        "sources.html",
        {
            "request": request,
            "title": "Sources",
            "current_user": current_user,
            "bootstrap_pending": not bool(settings and settings.miniflux_bootstrap_completed),
            "feeds": feeds,
            "source_by_url": source_by_url,
            "error": error or request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
        },
    )


@app.post("/sources/add")
def add_source(feed_url: str = Form(...), _: object = Depends(require_admin)):
    try:
        MinifluxClient().add_feed(feed_url=feed_url.strip())
        return RedirectResponse("/sources?ok=Feed+added", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/sources?error={str(exc)}", status_code=303)




@app.post("/sources/seed-defaults")
def seed_default_sources(db: Session = Depends(get_db), _: object = Depends(require_admin)):
    from app.services.source_catalog import seed_source_registry

    created = seed_source_registry(db)
    return RedirectResponse(f"/sources?ok=Seeded+{created}+default+sources", status_code=303)
@app.post("/sources/remove")
def remove_source(feed_id: int = Form(...), _: object = Depends(require_admin)):
    try:
        MinifluxClient().delete_feed(feed_id)
        return RedirectResponse("/sources?ok=Feed+removed", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/sources?error={str(exc)}", status_code=303)


@app.post("/sources/toggle")
def toggle_source(feed_id: int = Form(...), disabled: bool = Form(False), db: Session = Depends(get_db), _: object = Depends(require_admin)):
    try:
        MinifluxClient().set_feed_disabled(feed_id, disabled)
        # refresh local mirror
        feeds = MinifluxClient().list_feeds()
        _sync_sources_from_miniflux(db, feeds)
        return RedirectResponse("/sources?ok=Feed+updated", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/sources?error={str(exc)}", status_code=303)


@app.post("/sources/weight")
def update_source_weight(
    feed_url: str = Form(...),
    priority_weight: float = Form(1.0),
    source_tier: int = Form(3),
    poll_frequency_minutes: int = Form(30),
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    source = db.scalar(select(Source).where(Source.feed_url == feed_url))
    if source:
        source.priority_weight = max(0.1, min(priority_weight, 10.0))
        source.weight = source.priority_weight
        source.source_tier = max(1, min(source_tier, 3))
        source.poll_frequency_minutes = max(5, min(poll_frequency_minutes, 240))
        db.commit()
    return RedirectResponse("/sources?ok=Source+settings+updated", status_code=303)


@app.post("/sources/import-opml")
async def import_opml(file: UploadFile = File(...), _: object = Depends(require_admin)):
    try:
        text = (await file.read()).decode("utf-8")
        MinifluxClient().import_opml(text)
        return RedirectResponse("/sources?ok=OPML+imported", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/sources?error={str(exc)}", status_code=303)


@app.get("/sources/export-opml")
def export_opml(_: object = Depends(require_admin)):
    try:
        content = MinifluxClient().export_opml()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return Response(
            content=content,
            media_type="text/xml",
            headers={"Content-Disposition": f'attachment; filename=\"sources-{stamp}.opml\"'},
        )
    except Exception as exc:
        return RedirectResponse(f"/sources?error={str(exc)}", status_code=303)


@app.get("/setup/{step}", response_class=HTMLResponse)
def setup_wizard(step: int, request: Request, db: Session = Depends(get_db)):
    setup_load_error = None
    try:
        settings = db.scalar(select(AppSetting).limit(1))
        admin_user = db.scalar(select(User).where(User.is_admin.is_(True)).limit(1))
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Setup wizard query failed; attempting on-demand migrations: %s", exc)
        try:
            run_migrations()
            settings = db.scalar(select(AppSetting).limit(1))
            admin_user = db.scalar(select(User).where(User.is_admin.is_(True)).limit(1))
        except Exception as retry_exc:
            db.rollback()
            logger.exception("Setup wizard still unavailable after migration retry: %s", retry_exc)
            settings = None
            admin_user = None
            setup_load_error = "Could not load setup data. Verify database migrations and connectivity."

    if settings and settings.setup_completed:
        return RedirectResponse("/login?next=/onboarding", status_code=303)

    try:
        service_health = health()
    except Exception as exc:  # defensive fallback for setup UX
        logger.warning("Health check failed during setup wizard render: %s", exc)
        service_health = {"database": False, "miniflux": False, "meilisearch": False, "ollama": False, "worker_healthy": False, "scheduler_healthy": False}

    checks = _wizard_checks(service_health)
    step = max(1, min(step, 8))
    if settings:
        settings.setup_last_step = max(settings.setup_last_step or 1, step)
        db.commit()

    return templates.TemplateResponse(
        name="setup_wizard.html",
        context={
            "request": request,
            "title": "Setup Wizard",
            "step": step,
            "settings": settings,
            "admin_user": admin_user,
            "checks": checks,
            "error": request.query_params.get("error") or setup_load_error,
            "ok": request.query_params.get("ok"),
            "connection_ok": request.query_params.get("connection_ok"),
        },
    )


def _wizard_checks(service_health: dict) -> dict[str, dict[str, str]]:
    checks: dict[str, dict[str, str]] = {}
    checks["database"] = {"status": "pass" if service_health.get("database") else "fail", "message": "App database"}
    checks["miniflux"] = {"status": "pass" if service_health.get("miniflux") else "warn", "message": "Feed ingestion service (Miniflux)"}
    checks["meilisearch"] = {"status": "pass" if service_health.get("meilisearch") else "warn", "message": "Search service (Meilisearch)"}
    checks["ollama"] = {"status": "pass" if service_health.get("ollama") else "warn", "message": "Local AI service (Ollama)"}
    worker_ok = bool(service_health.get("worker_healthy"))
    beat_ok = bool(service_health.get("scheduler_healthy"))
    checks["worker"] = {"status": "pass" if worker_ok else "warn", "message": "Background worker"}
    checks["scheduler"] = {"status": "pass" if beat_ok else "warn", "message": "Background scheduler"}
    return checks


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_user)):
    if not _is_setup_completed(db):
        return RedirectResponse("/setup/1", status_code=303)
    settings = db.scalar(select(AppSetting).limit(1))
    return templates.TemplateResponse(
        "setup_complete.html",
        {
            "request": request,
            "title": "You're all set",
            "current_user": current_user,
            "settings": settings,
            "bootstrap_pending": not bool(settings and settings.miniflux_bootstrap_completed),
        },
    )


@app.post("/setup/{step}")
def setup_wizard_submit(
    step: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_username: str = Form("admin"),
    admin_password: str = Form(""),
    current_password: str = Form(""),
    region: str = Form("global"),
    local_relevance_preference: str = Form("medium"),
    topics: str = Form("world,politics,business,technology"),
    source_preset: str = Form("balanced"),
    llm_provider: str = Form("ollama"),
    miniflux_base_url: str = Form(""),
    miniflux_admin_username: str = Form(""),
    miniflux_admin_password: str = Form(""),
    ollama_base_url: str = Form(""),
    ollama_chat_model: str = Form(""),
    ollama_embed_model: str = Form(""),
    openai_api_key: str = Form(""),
    openai_model: str = Form("gpt-4.1-mini"),
    openai_fallback_enabled: bool = Form(False),
    test_connection: bool = Form(False),
    enable_social_context: bool = Form(False),
    enable_reddit_context: bool = Form(False),
    enable_x_context: bool = Form(False),
):
    settings = db.scalar(select(AppSetting).limit(1))
    if not settings:
        return RedirectResponse("/setup/1?error=Settings+not+initialized", status_code=303)
    if settings.setup_completed:
        return RedirectResponse("/onboarding", status_code=303)

    step = max(1, min(step, 8))
    settings.setup_last_step = max(settings.setup_last_step or 1, step)

    if step == 2:
        checks = _wizard_checks(health())
        if checks["database"]["status"] == "fail":
            db.commit()
            return RedirectResponse("/setup/2?error=Database+must+be+healthy+before+continuing", status_code=303)
        db.commit()
        return RedirectResponse("/setup/3", status_code=303)

    if step == 3:
        admin_user = db.scalar(select(User).where(User.is_admin.is_(True)).limit(1))
        if not admin_user:
            if len(admin_username.strip()) < 3 or len(admin_password) < 8:
                db.commit()
                return RedirectResponse("/setup/3?error=Use+a+username+3%2B+chars+and+password+8%2B+chars", status_code=303)
            db.add(User(username=admin_username.strip(), hashed_password=hash_password(admin_password), is_admin=True))
            db.commit()
            return RedirectResponse("/setup/4", status_code=303)

        # existing admin: optional password update if provided
        if admin_password.strip():
            if len(admin_password) < 8:
                db.commit()
                return RedirectResponse("/setup/3?error=New+password+must+be+8%2B+chars", status_code=303)
            admin_user.username = admin_username.strip() or admin_user.username
            admin_user.hashed_password = hash_password(admin_password)
        db.commit()
        return RedirectResponse("/setup/4", status_code=303)

    if step == 4:
        settings.region = region.strip() or "global"
        settings.local_relevance_preference = local_relevance_preference if local_relevance_preference in {"low", "medium", "high"} else "medium"
        settings.topics = [t.strip() for t in topics.split(",") if t.strip()]
        db.commit()
        return RedirectResponse("/setup/5", status_code=303)

    if step == 5:
        allowed_presets = {"balanced", "us_national", "international", "tech_business", "custom"}
        settings.source_preset = source_preset if source_preset in allowed_presets else "balanced"
        db.commit()
        return RedirectResponse("/setup/6", status_code=303)

    if step == 6:
        settings.llm_provider = llm_provider if llm_provider in {"ollama", "openai", "hybrid"} else "ollama"
        settings.miniflux_base_url = miniflux_base_url.strip() or settings.miniflux_base_url
        settings.miniflux_admin_username = miniflux_admin_username.strip() or settings.miniflux_admin_username
        settings.miniflux_admin_password = miniflux_admin_password.strip() or settings.miniflux_admin_password
        settings.ollama_base_url = ollama_base_url.strip() or settings.ollama_base_url
        settings.ollama_chat_model = ollama_chat_model.strip() or settings.ollama_chat_model
        settings.ollama_embed_model = ollama_embed_model.strip() or settings.ollama_embed_model
        settings.openai_api_key = openai_api_key.strip() or settings.openai_api_key
        settings.openai_model = openai_model.strip() or settings.openai_model
        settings.openai_fallback_enabled = openai_fallback_enabled
        db.commit()

        if test_connection:
            llm = LLMService()
            ok = llm.ollama_health() if settings.llm_provider in {"ollama", "hybrid"} else bool(settings.openai_api_key)
            return RedirectResponse(f"/setup/6?connection_ok={'1' if ok else '0'}", status_code=303)
        return RedirectResponse("/setup/7", status_code=303)

    if step == 7:
        settings.enable_social_context = enable_social_context
        settings.enable_reddit_context = enable_reddit_context
        settings.enable_x_context = enable_x_context
        db.commit()
        return RedirectResponse("/setup/8", status_code=303)

    if step == 8:
        settings.setup_completed = True
        settings.miniflux_bootstrap_completed = False
        settings.setup_last_step = 8
        db.commit()
        retry_miniflux_bootstrap_task.delay()
        run_pipeline_task.delay()
        return RedirectResponse("/onboarding", status_code=303)

    db.commit()
    return RedirectResponse(f"/setup/{step + 1}", status_code=303)
