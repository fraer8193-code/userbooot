import os
import json
import asyncio
from pathlib import Path
from aiohttp import web
from afk_trainer import trainer

WEB_DIR = Path(__file__).parent / "web"
PORT = 5050

async def handle_index(request):
    return web.FileResponse(WEB_DIR / "index.html")

async def handle_static(request):
    filename = request.match_info.get("filename")
    filepath = WEB_DIR / filename
    if filepath.exists() and filepath.is_file():
        return web.FileResponse(filepath)
    return web.Response(status=404, text="Not found")

async def handle_status(request):
    return web.json_response(trainer.get_status())

async def handle_start(request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    duration = data.get("duration_seconds", 3600)
    if not trainer.is_training:
        asyncio.create_task(trainer.run_training_loop(target_duration_seconds=duration))
    elif trainer.is_paused:
        trainer.is_paused = False
        trainer.log("Обучение возобновлено.")

    return web.json_response({"status": "started", "duration_seconds": duration})

async def handle_pause(request):
    if trainer.is_training:
        trainer.is_paused = not trainer.is_paused
        trainer.log("Обучение на паузе." if trainer.is_paused else "Обучение возобновлено.")
    return web.json_response({"status": "paused" if trainer.is_paused else "resumed"})

async def handle_stop(request):
    if trainer.is_training:
        trainer.should_stop = True
        trainer.log("Остановка обучения...")
    return web.json_response({"status": "stopping"})

async def handle_predict(request):
    try:
        data = await request.json()
        prompt = data.get("text", "")
    except Exception:
        prompt = ""

    if not prompt:
        return web.json_response({"type": "text", "text": "че?"})

    response = await trainer.generate_response(prompt)
    text_to_eval = response.get("text", "")
    if text_to_eval:
        eval_res = await trainer.evaluate_response_with_judge(prompt, text_to_eval, force_judge=True)
        response["judge"] = eval_res
    return web.json_response(response)

def create_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/start", handle_start)
    app.router.add_post("/api/pause", handle_pause)
    app.router.add_post("/api/stop", handle_stop)
    app.router.add_post("/api/predict", handle_predict)
    app.router.add_get("/{filename:[a-zA-Z0-9_.-]+}", handle_static)
    return app

if __name__ == "__main__":
    print(f"AFK AI Trainer Dashboard started on http://localhost:{PORT}")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)
