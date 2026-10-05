from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="corridor-api")


def todo(name: str) -> JSONResponse:
    return JSONResponse({"todo": name}, status_code=501)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/vehicles/bind")
def vehicles_bind():
    return todo("vehicles_bind")


@app.post("/incidents")
def incidents():
    return todo("incidents")


@app.post("/runs")
def runs():
    return todo("runs")


@app.post("/triage")
def triage():
    return todo("triage")


@app.post("/log")
def log():
    return todo("log")


@app.post("/brief")
def brief():
    return todo("brief")


@app.post("/location")
def location():
    return todo("location")


@app.post("/ack")
def ack():
    return todo("ack")
