"""
SybilScope FastAPI Server

Endpoints:
  GET  /                    → home.html (list of saved analyses)
  GET  /graph               → index.html (D3 graph viewer)
  GET  /analyses            → list all *_output.json files
  GET  /analysis/{name}     → return a specific analysis JSON
  POST /analyze             → run JAC on a cache file, return JSON
  static files served from frontend/
"""

import json
import os
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
FRONTEND_DIR = BASE_DIR / "frontend"
SYBILSCOPE_DIR = BASE_DIR / "sybilscope"
VENV_JAC = BASE_DIR / "venv" / "bin" / "jac"

app = FastAPI(title="SybilScope")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def home():
    return FileResponse(str(FRONTEND_DIR / "home.html"))


@app.get("/graph")
def graph():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/analyses")
def list_analyses():
    """List all saved analysis JSON files."""
    files = sorted(BASE_DIR.glob("*_output.json"))
    result = []
    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)
            summary = data.get("summary", {})
            result.append({
                "name": f.stem.replace("_output", ""),
                "file": f.name,
                "total_classified": summary.get("total_classified", 0),
                "flagged": summary.get("flagged", 0),
                "clusters_found": summary.get("clusters_found", 0),
                "common_funder": summary.get("common_funder", ""),
                "title": summary.get("title", ""),
                "description": summary.get("description", ""),
            })
        except Exception:
            continue
    return JSONResponse(result)


@app.get("/analysis/{name}")
def get_analysis(name: str):
    """Return a specific analysis JSON by name."""
    # try {name}_output.json first, then {name}.json
    for candidate in [BASE_DIR / f"{name}_output.json", BASE_DIR / f"{name}.json"]:
        if candidate.exists():
            with open(candidate) as f:
                return JSONResponse(json.load(f))
    raise HTTPException(status_code=404, detail=f"Analysis '{name}' not found")


class AnalyzeRequest(BaseModel):
    cache: str = "demo_data_cache"  # cache file name without .json
    output: str = "analysis"        # output name without _output.json


@app.post("/analyze")
def run_analysis(req: AnalyzeRequest):
    """Run JAC on a cache file and return the resulting JSON."""
    cache_path = BASE_DIR / f"{req.cache}.json"
    if not cache_path.exists():
        raise HTTPException(status_code=404, detail=f"Cache '{req.cache}.json' not found")

    output_path = BASE_DIR / f"{req.output}_output.json"
    jac_bin = str(VENV_JAC) if VENV_JAC.exists() else "jac"

    env = os.environ.copy()
    env["SYBILSCOPE_OUTPUT"] = str(output_path)
    env["SYBILSCOPE_CACHE"] = str(cache_path)

    try:
        proc = subprocess.run(
            [jac_bin, "run", "main.jac"],
            cwd=str(SYBILSCOPE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Analysis timed out (300s)")

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr[-2000:])

    if not output_path.exists():
        raise HTTPException(status_code=500, detail="JAC ran but produced no output JSON")

    with open(output_path) as f:
        return JSONResponse(json.load(f))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"SybilScope running at http://localhost:{port}")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
