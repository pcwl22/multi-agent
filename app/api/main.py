from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from filelock import Timeout

from app.config.settings import Settings
from app.models.schemas import Approval, TaskRequest
from app.services.tasks import TaskService


def create_app(settings: Settings | None = None, service: TaskService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.tasks = service or TaskService(settings or Settings())
        yield
        if service is None:
            app.state.tasks.close()

    api = FastAPI(title="RepoPilot", version="0.1.0", lifespan=lifespan)

    # Local developer tool: reject browser-origin cross-site writes and DNS rebinding.
    @api.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Loopback host required"}, status_code=403)
        if request.method == "POST" and request.headers.get("origin"):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"detail": "Browser-origin writes disabled; use local UI backend"}, status_code=403
            )
        return await call_next(request)

    def tasks(request: Request) -> TaskService:
        return request.app.state.tasks

    def get(request, task_id):
        try:
            return tasks(request).get(task_id)
        except KeyError as exc:
            raise HTTPException(404, "Unknown task") from exc

    @api.post("/api/tasks", status_code=202)
    def create_task(body: TaskRequest, background: BackgroundTasks, request: Request):
        try:
            task = tasks(request).create(body)
        except (ValueError, OSError, httpx.HTTPError) as exc:
            raise HTTPException(400, str(exc)) from exc
        if task["execution_status"] == "queued":
            background.add_task(tasks(request).run, task["task_id"])
        return task

    @api.get("/api/tasks/{task_id}")
    def get_task(task_id: str, request: Request):
        return get(request, task_id)

    @api.get("/api/tasks/{task_id}/events")
    def events(task_id: str, request: Request):
        state = get(request, task_id)
        return {"events": state["execution_history"], "retrieval": state["retrieval_history"]}

    @api.get("/api/tasks/{task_id}/diff")
    def diff(task_id: str, request: Request):
        get(request, task_id)
        return tasks(request).diff(task_id)

    def decide(task_id, request, approved, body):
        get(request, task_id)
        try:
            return tasks(request).decide(task_id, approved, body.diff_digest,
                                         candidate_id=body.candidate_id)
        except (ValueError, Timeout) as exc:
            raise HTTPException(409, str(exc)) from exc

    @api.post("/api/tasks/{task_id}/approve")
    def approve(task_id: str, body: Approval, request: Request):
        return decide(task_id, request, True, body)

    @api.post("/api/tasks/{task_id}/reject")
    def reject(task_id: str, body: Approval, request: Request):
        return decide(task_id, request, False, body)

    @api.post("/api/tasks/{task_id}/pr")
    def publish_pr(task_id: str, body: Approval, request: Request):
        get(request, task_id)
        try:
            return tasks(request).publish(task_id, body.diff_digest, candidate_id=body.candidate_id)
        except (ValueError, Timeout) as exc:
            raise HTTPException(409, str(exc)) from exc

    @api.post("/api/tasks/{task_id}/resume", status_code=202)
    def resume(task_id: str, background: BackgroundTasks, request: Request):
        get(request, task_id)
        try:
            tasks(request).check_resume(task_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        background.add_task(tasks(request).run, task_id)
        return {"task_id": task_id, "status": "resume_requested"}

    return api


app = create_app()
