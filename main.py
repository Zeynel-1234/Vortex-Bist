from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"servis": "TEST", "durum": "OK"}

@app.get("/symbols")
def symbols():
    return {"test": "symbols endpoint works"}

@app.get("/analyze/{symbol}")
def analyze(symbol: str):
    return {"symbol": symbol, "test": "analyze works"}

@app.get("/scan")
def scan():
    return {"test": "scan works"}

@app.get("/_debug_routes")
def debug():
    return {"routes": [r.path for r in app.routes]}
