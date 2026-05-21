from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import random

app = FastAPI()

# ---------------------------------------------------------------------
# Temporary in-memory storage.
# This resets when the server restarts.
# Good for first sync test. Later we move POIs to a real database.
# ---------------------------------------------------------------------

beacons = {}

poi_locations = {
    "medical": {
        "id": "medical",
        "name": "Medical",
        "category": "Services & Amenities",
        "map_x": 0.57,
        "map_y": 0.64,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "restrooms": {
        "id": "restrooms",
        "name": "Restrooms",
        "category": "Services & Amenities",
        "map_x": 0.51,
        "map_y": 0.62,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "water": {
        "id": "water",
        "name": "Water Stations",
        "category": "Services & Amenities",
        "map_x": 0.46,
        "map_y": 0.56,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "guest_services": {
        "id": "guest_services",
        "name": "Guest Services",
        "category": "Services & Amenities",
        "map_x": 0.63,
        "map_y": 0.73,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "info_lost_found": {
        "id": "info_lost_found",
        "name": "Info + Lost & Found",
        "category": "Services & Amenities",
        "map_x": 0.55,
        "map_y": 0.58,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "lightning": {
        "id": "lightning",
        "name": "Lightning",
        "category": "Stages",
        "map_x": 0.36,
        "map_y": 0.42,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "thunder": {
        "id": "thunder",
        "name": "Thunder",
        "category": "Stages",
        "map_x": 0.55,
        "map_y": 0.42,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "woogie": {
        "id": "woogie",
        "name": "Woogie",
        "category": "Stages",
        "map_x": 0.57,
        "map_y": 0.76,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "stacks": {
        "id": "stacks",
        "name": "Stacks",
        "category": "Stages",
        "map_x": 0.48,
        "map_y": 0.74,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "grand_artique": {
        "id": "grand_artique",
        "name": "Grand Artique",
        "category": "Stages",
        "map_x": 0.42,
        "map_y": 0.66,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "lighthouse": {
        "id": "lighthouse",
        "name": "Lighthouse & Moon Room",
        "category": "Stages",
        "map_x": 0.48,
        "map_y": 0.68,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "sunset_plaza": {
        "id": "sunset_plaza",
        "name": "Sunset Plaza",
        "category": "Plazas",
        "map_x": 0.18,
        "map_y": 0.38,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "high_noon_plaza": {
        "id": "high_noon_plaza",
        "name": "High Noon Plaza",
        "category": "Plazas",
        "map_x": 0.51,
        "map_y": 0.20,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "sunrise_plaza": {
        "id": "sunrise_plaza",
        "name": "Sunrise Plaza",
        "category": "Plazas",
        "map_x": 0.80,
        "map_y": 0.44,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "atlaswyld_entrance": {
        "id": "atlaswyld_entrance",
        "name": "Atlaswyld Entrance",
        "category": "Entrances",
        "map_x": 0.69,
        "map_y": 0.80,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
    "main_entrance": {
        "id": "main_entrance",
        "name": "Main Entrance",
        "category": "Entrances",
        "map_x": 0.50,
        "map_y": 0.87,
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "updated_at": None,
        "updated_by": None,
    },
}


# ---------------------------------------------------------------------
# Original temporary beacon models/routes
# ---------------------------------------------------------------------

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
        "message": "Use /beacons for temporary beacons and /pois for festival POI GPS sync.",
        "routes": [
            "POST /beacons",
            "GET /beacons/{code}",
            "GET /pois",
            "GET /pois/{poi_id}",
            "PUT /pois/{poi_id}/location",
        ],
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


# ---------------------------------------------------------------------
# New POI GPS sync models/routes
# ---------------------------------------------------------------------

class PoiResponse(BaseModel):
    id: str
    name: str
    category: str
    map_x: float
    map_y: float
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class UpdatePoiLocationRequest(BaseModel):
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None
    updated_by: Optional[str] = "admin"


@app.get("/pois", response_model=List[PoiResponse])
def get_pois():
    return list(poi_locations.values())


@app.get("/pois/{poi_id}", response_model=PoiResponse)
def get_poi(poi_id: str):
    poi_id = poi_id.strip()

    if poi_id not in poi_locations:
        raise HTTPException(status_code=404, detail="POI not found")

    return poi_locations[poi_id]


@app.put("/pois/{poi_id}/location", response_model=PoiResponse)
def update_poi_location(poi_id: str, request: UpdatePoiLocationRequest):
    poi_id = poi_id.strip()

    if poi_id not in poi_locations:
        raise HTTPException(status_code=404, detail="POI not found")

    poi_locations[poi_id]["latitude"] = request.latitude
    poi_locations[poi_id]["longitude"] = request.longitude
    poi_locations[poi_id]["accuracy_meters"] = request.accuracy_meters
    poi_locations[poi_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    poi_locations[poi_id]["updated_by"] = request.updated_by or "admin"

    return poi_locations[poi_id]
