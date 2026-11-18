import os
import re
import glob
import json
import hashlib
import secrets
import sqlite3
from contextlib import closing

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel, Field
from typing import Literal
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HYBRID_PATH = os.path.join(BASE_DIR, "mental_health_hybrid.pkl")
OLD_PATH = os.path.join(BASE_DIR, "mental_helth_model.pkl")

FEATURES = ['Study_Hours', 'Age', 'Avg_Daily_Usage_Hours', 'Daily_Unlocks', 'Physical_Activity_Hours',
            'Sleep_Hours_Per_Night', 'Stress_Level', 'Gender', 'Academic_Level',
            'Most_Used_Platform', 'Purpose_Of_Use', 'Country']

if os.path.exists(HYBRID_PATH):
    bundle = joblib.load(HYBRID_PATH)
    lin, rf, FEATURES = bundle["lin"], bundle["rf"], bundle["features"]

    def ml_predict(row):
        return float(lin.predict(row)[0] + rf.predict(row)[0])
elif os.path.exists(OLD_PATH):
    old_model = joblib.load(OLD_PATH)

    def ml_predict(row):
        return float(old_model.predict(row)[0])
else:
    raise FileNotFoundError(
        "Model file not found. Put mental_health_hybrid.pkl (or mental_helth_model.pkl) next to main.py."
    )

top_countries = ['Other', 'India', 'USA', 'Canada', 'Australia', 'UK', 'Germany', 'Mexico', 'Turkey', 'France']

TRAIN_RANGE = {
    "age": (18, 24, "Age"),
    "avg_daily_usage_hours": (1, 8.8, "Screen time"),
    "daily_unlocks": (62, 273, "Phone unlocks"),
    "study_hours": (0.3, 8.3, "Study hours"),
    "physical_activity_hours": (0, 4.1, "Physical activity"),
    "sleep_hours_per_night": (3.6, 9.9, "Sleep"),
}

def health_adjustments(data):
    adj = []
    if data.sleep_hours_per_night < 6:
        pen = min(0.3 * (6 - data.sleep_hours_per_night), 1.8)
        adj.append((-pen, f"Sleep under 6 hrs ({data.sleep_hours_per_night} hrs)"))
    if data.physical_activity_hours < 0.5:
        adj.append((-0.3, "Very low physical activity"))
    if data.stress_level == "Very High":
        adj.append((-0.6, "Very high stress"))
    elif data.stress_level == "High":
        adj.append((-0.3, "High stress"))
    return adj


# ======================================================================
#  DATABASE + AUTH
# ======================================================================
DB_PATH = os.path.join(BASE_DIR, "users.db")

# CSV ka naam kuch bhi ho (spaces / underscores / (1)), folder ki "mental" wali CSV pick ho jayegi
_csvs = glob.glob(os.path.join(BASE_DIR, "*.csv"))
CSV_PATH = next(
    (p for p in _csvs if "mental" in os.path.basename(p).lower()),
    _csvs[0] if _csvs else os.path.join(BASE_DIR, "dataset.csv"),
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(db()) as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw TEXT, salt TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER)")
        c.execute("""CREATE TABLE IF NOT EXISTS predictions(
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        score REAL, model_score REAL, inputs TEXT)""")
        c.commit()


def hash_pw(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000).hex()


def new_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token, user_id) VALUES(?, ?)", (token, user_id))
    conn.commit()
    return token


def current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Please log in first.")
    token = authorization[7:]
    with closing(db()) as c:
        row = c.execute(
            "SELECT u.id, u.name, u.email FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return {"id": row["id"], "name": row["name"], "email": row["email"], "token": token}


init_db()
DATASET = pd.read_csv(CSV_PATH) if os.path.exists(CSV_PATH) else None


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class StudentData(BaseModel):
    age: int = Field(..., ge=10, le=100)
    gender: Literal['Male', 'Female']
    country: str
    academic_level: Literal['Undergraduate', 'Graduate', 'High School']
    most_used_platform: Literal['Facebook', 'LinkedIn', 'Instagram', 'Snapchat', 'Twitter', 'YouTube',
                                'TikTok', 'LINE', 'KakaoTalk', 'VKontakte', 'WhatsApp', 'WeChat']
    purpose_of_use: Literal['Networking', 'Education', 'Entertainment', 'News']
    avg_daily_usage_hours: float = Field(..., ge=0, le=24)
    daily_unlocks: int = Field(..., ge=0, le=1000)
    study_hours: float = Field(..., ge=0, le=24)
    physical_activity_hours: float = Field(..., ge=0, le=24)
    sleep_hours_per_night: float = Field(..., ge=0, le=24)
    stress_level: Literal['Medium', 'Low', 'Very High', 'High']


class RegisterIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    email: str
    password: str = Field(..., min_length=6, max_length=128)


class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/register")
def register(body: RegisterIn):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    salt = secrets.token_hex(16)
    with closing(db()) as c:
        try:
            cur = c.execute("INSERT INTO users(name, email, pw, salt) VALUES(?,?,?,?)",
                            (body.name.strip(), email, hash_pw(body.password, salt), salt))
            c.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="This email is already registered. Try logging in.")
        token = new_session(c, cur.lastrowid)
    return {"token": token, "user": {"name": body.name.strip(), "email": email}}


@app.post("/login")
def login(body: LoginIn):
    email = body.email.strip().lower()
    with closing(db()) as c:
        row = c.execute("SELECT id, name, email, pw, salt FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not secrets.compare_digest(row["pw"] or "", hash_pw(body.password, row["salt"])):
            raise HTTPException(status_code=401, detail="Wrong email or password.")
        token = new_session(c, row["id"])
    return {"token": token, "user": {"name": row["name"], "email": row["email"]}}


@app.post("/logout")
def logout(user=Depends(current_user)):
    with closing(db()) as c:
        c.execute("DELETE FROM sessions WHERE token = ?", (user["token"],))
        c.commit()
    return {"ok": True}


@app.get("/me")
def me(user=Depends(current_user)):
    return {"name": user["name"], "email": user["email"]}


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/predict")
def predict(data: StudentData, user=Depends(current_user)):
    country = next((c for c in top_countries if c.lower() == data.country.strip().lower()), 'Other')

    row = pd.DataFrame([{
        'Study_Hours': data.study_hours,
        'Age': data.age,
        'Avg_Daily_Usage_Hours': data.avg_daily_usage_hours,
        'Daily_Unlocks': data.daily_unlocks,
        'Physical_Activity_Hours': data.physical_activity_hours,
        'Sleep_Hours_Per_Night': data.sleep_hours_per_night,
        'Stress_Level': data.stress_level,
        'Gender': data.gender,
        'Academic_Level': data.academic_level,
        'Most_Used_Platform': data.most_used_platform,
        'Purpose_Of_Use': data.purpose_of_use,
        'Country': country,
    }])[FEATURES]

    try:
        score = ml_predict(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model error: {e}")

    model_score = score
    adjustments = health_adjustments(data)
    score = max(0.0, min(10.0, score + sum(a for a, _ in adjustments)))

    warnings = []
    for key, (lo, hi, label) in TRAIN_RANGE.items():
        v = getattr(data, key)
        if v < lo or v > hi:
            warnings.append(f"{label} ({v}) is outside the typical range {lo}-{hi}, so this estimate is less reliable.")

    with closing(db()) as c:
        c.execute("INSERT INTO predictions(user_id, score, model_score, inputs) VALUES(?,?,?,?)",
                  (user["id"], round(score, 2), round(model_score, 2),
                   json.dumps(data.model_dump() if hasattr(data, "model_dump") else data.dict())))
        c.commit()

    return {
        "predicted_mental_health_score": round(score, 2),
        "model_score": round(max(0.0, min(10.0, model_score)), 2),
        "adjustments": [{"points": round(a, 2), "reason": r} for a, r in adjustments],
        "warnings": warnings,
    }


# ======================================================================
#  HISTORY + ANALYTICS
# ======================================================================
@app.get("/history")
def history(user=Depends(current_user)):
    with closing(db()) as c:
        rows = c.execute(
            "SELECT id, created_at, score, model_score, inputs FROM predictions WHERE user_id = ? ORDER BY id DESC LIMIT 50",
            (user["id"],),
        ).fetchall()
    out = []
    for r in rows:
        inp = json.loads(r["inputs"])
        out.append({"id": r["id"], "created_at": r["created_at"], "score": r["score"],
                    "sleep": inp.get("sleep_hours_per_night"), "screen": inp.get("avg_daily_usage_hours"),
                    "stress": inp.get("stress_level")})
    return out


def _group(df, col, order=None, top=None):
    g = df.groupby(col)["Mental_Health_Score"].agg(["mean", "count"]).reset_index()
    if order:
        g[col] = pd.Categorical(g[col], categories=order, ordered=True)
        g = g.sort_values(col)
    else:
        g = g.sort_values("mean", ascending=False)
    if top:
        g = g.sort_values("count", ascending=False).head(top).sort_values("mean", ascending=False)
    return {"labels": g[col].astype(str).tolist(), "avg": g["mean"].round(2).tolist(), "count": g["count"].tolist()}


def _bucket(df, col, bins, labels):
    b = pd.cut(df[col], bins=bins, labels=labels, right=False)
    g = df.groupby(b, observed=True)["Mental_Health_Score"].agg(["mean", "count"]).reset_index()
    return {"labels": g[col].astype(str).tolist(), "avg": g["mean"].round(2).tolist(), "count": g["count"].tolist()}


@app.get("/analytics")
def analytics(user=Depends(current_user)):
    if DATASET is None:
        raise HTTPException(status_code=404, detail="Dataset CSV not found next to main.py.")
    df = DATASET
    y = df["Mental_Health_Score"]

    hist_counts, edges = np.histogram(y, bins=np.arange(3, 10.5, 0.5))
    num_cols = ["Age", "Avg_Daily_Usage_Hours", "Daily_Unlocks", "Study_Hours",
                "Physical_Activity_Hours", "Sleep_Hours_Per_Night"]
    corr = df[num_cols].corrwith(y).round(3).sort_values()
    sample = df.sample(min(400, len(df)), random_state=1)

    return {
        "kpis": {
            "students": int(len(df)),
            "avg_score": round(float(y.mean()), 2),
            "avg_screen": round(float(df["Avg_Daily_Usage_Hours"].mean()), 2),
            "avg_sleep": round(float(df["Sleep_Hours_Per_Night"].mean()), 2),
            "avg_activity": round(float(df["Physical_Activity_Hours"].mean()), 2),
            "high_stress_pct": round(float(df["Stress_Level"].isin(["High", "Very High"]).mean() * 100), 1),
            "countries": int(df["Country"].nunique()),
        },
        "distribution": {"labels": [f"{edges[i]:.1f}-{edges[i+1]:.1f}" for i in range(len(hist_counts))],
                         "count": hist_counts.tolist()},
        "by_stress": _group(df, "Stress_Level", order=["Low", "Medium", "High", "Very High"]),
        "by_platform": _group(df, "Most_Used_Platform"),
        "by_academic": _group(df, "Academic_Level", order=["High School", "Undergraduate", "Graduate"]),
        "by_gender": _group(df, "Gender"),
        "by_purpose": _group(df, "Purpose_Of_Use"),
        "by_country": _group(df, "Country", top=8),
        "by_screen": _bucket(df, "Avg_Daily_Usage_Hours", [0, 2, 4, 6, 8, 100], ["<2h", "2-4h", "4-6h", "6-8h", "8h+"]),
        "by_sleep": _bucket(df, "Sleep_Hours_Per_Night", [0, 5, 6, 7, 8, 24], ["<5h", "5-6h", "6-7h", "7-8h", "8h+"]),
        "by_activity": _bucket(df, "Physical_Activity_Hours", [0, 0.5, 1, 2, 3, 24], ["<0.5h", "0.5-1h", "1-2h", "2-3h", "3h+"]),
        "correlation": {"labels": [c.replace("_", " ") for c in corr.index], "value": corr.tolist()},
        "scatter": {"screen": [{"x": float(a), "y": float(b)} for a, b in zip(sample["Avg_Daily_Usage_Hours"], sample["Mental_Health_Score"])]},
    }