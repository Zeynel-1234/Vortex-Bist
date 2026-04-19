from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
import time
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import yfinance as yf

from indicators import analyze_symbol
from symbols import get_all, to_yf, from_yf

app = FastAPI(title="Fraktal Kahin", version="1.0.0")

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

# --- TEMEL ROUTE'LAR (TEST İÇİN) ---
@app.get("/")
def root():
    return {"servis": "TEST", "durum": "OK"}

@app.get("/symbols")
def symbols():
    return {"test": "symbols endpoint works"}

@app.get("/analyze/{symbol}")
def analyze(symbol: str):
    return {"symbol": symbol, "test": "analyze work"}

@app.get("/scan")
def scan():
    return {"test": "scan works"}

@app.get("/_debug_routes")
def debug():
    return {"routes": [r.path for r in app.routes]}
