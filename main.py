from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import random

app = FastAPI()

# Temporary in-memory storage.
# This resets when the server restarts.
beacons = {}


class CreateBeaconRequest(BaseModel):
    name: str
    lat: float
    lon: float


class BeaconResponse(BaseModel):
    code: str
    name: str
    lat: float
    lon: float
    expires_at: str


def generate_code() -> str:
    for _ in range(20):
        code = str(random.randint(100000, 999999))
        if code not in beacons:
            return code
    raise RuntimeError("Could not generate unique code")


@app.get("/")
def root():
    return {
        "status": "Beacon server running",
        "message": "Use POST /beacons to create a beacon and GET /beacons/{code} to find one."
    }


@app.post("/beacons", response_model=BeaconResponse)
def create_beacon(request: CreateBeaconRequest):
    code = generate_code()

    expires_at = datetime.now(timezone.utc) + timedelta(hours=2)

    beacons[code] = {
        "code": code,
        "name": request.name.strip() or "Beacon",
        "lat": request.lat,
        "lon": request.lon,
        "expires_at": expires_at,
    }

    return {
        "code": code,
        "name": beacons[code]["name"],
        "lat": request.lat,
        "lon": request.lon,
        "expires_at": expires_at.isoformat(),
    }


@app.get("/beacons/{code}", response_model=BeaconResponse)
def get_beacon(code: str):
    code = code.strip()

    if code not in beacons:
        raise HTTPException(status_code=404, detail="Beacon code not found")

    beacon = beacons[code]

    if datetime.now(timezone.utc) > beacon["expires_at"]:
        del beacons[code]
        raise HTTPException(status_code=410, detail="Beacon code expired")

    return {
        "code": beacon["code"],
        "name": beacon["name"],
        "lat": beacon["lat"],
        "lon": beacon["lon"],
        "expires_at": beacon["expires_at"].isoformat(),
    }
