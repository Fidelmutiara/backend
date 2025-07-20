from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict
import sqlite3
from fastapi.middleware.cors import CORSMiddleware
import math

app = FastAPI(title="Tofico Syrup DSS API")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
def init_db():
    conn = sqlite3.connect('tofico.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        address TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS criteria (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        weight REAL NOT NULL,
        type TEXT NOT NULL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS location_criteria (
        location_id INTEGER,
        criteria_id TEXT,
        value REAL NOT NULL,
        PRIMARY KEY (location_id, criteria_id),
        FOREIGN KEY (location_id) REFERENCES locations(id),
        FOREIGN KEY (criteria_id) REFERENCES criteria(id)
    )''')
    
    conn.commit()
    conn.close()

init_db()

# Pydantic models
class LocationBase(BaseModel):
    name: str
    address: str
    latitude: float
    longitude: float
    criteria: Dict[str, float]

class Location(LocationBase):
    id: int

class CriteriaBase(BaseModel):
    id: str
    name: str
    weight: float
    type: str

class Criteria(CriteriaBase):
    pass

# Database operations
def get_db():
    conn = sqlite3.connect('tofico.db')
    conn.row_factory = sqlite3.Row
    return conn

# Location endpoints
@app.get("/locations", response_model=List[Location])
async def get_locations():
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM locations")
    locations = c.fetchall()
    
    result = []
    for loc in locations:
        c.execute("SELECT criteria_id, value FROM location_criteria WHERE location_id = ?", (loc['id'],))
        criteria_values = {row['criteria_id']: row['value'] for row in c.fetchall()}
        
        result.append({
            "id": loc['id'],
            "name": loc['name'],
            "address": loc['address'],
            "latitude": loc['latitude'],
            "longitude": loc['longitude'],
            "criteria": criteria_values
        })
    
    conn.close()
    return result

@app.post("/locations", response_model=Location)
async def create_location(location: LocationBase):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("INSERT INTO locations (name, address, latitude, longitude) VALUES (?, ?, ?, ?)",
              (location.name, location.address, location.latitude, location.longitude))
    location_id = c.lastrowid
    
    for criteria_id, value in location.criteria.items():
        c.execute("INSERT INTO location_criteria (location_id, criteria_id, value) VALUES (?, ?, ?)",
                  (location_id, criteria_id, value))
    
    conn.commit()
    conn.close()
    
    return {**location.dict(), "id": location_id}

@app.put("/locations/{location_id}", response_model=Location)
async def update_location(location_id: int, location: LocationBase):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("UPDATE locations SET name = ?, address = ?, latitude = ?, longitude = ? WHERE id = ?",
              (location.name, location.address, location.latitude, location.longitude, location_id))
    
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Location not found")
    
    c.execute("DELETE FROM location_criteria WHERE location_id = ?", (location_id,))
    for criteria_id, value in location.criteria.items():
        c.execute("INSERT INTO location_criteria (location_id, criteria_id, value) VALUES (?, ?, ?)",
                  (location_id, criteria_id, value))
    
    conn.commit()
    conn.close()
    
    return {**location.dict(), "id": location_id}

@app.delete("/locations/{location_id}")
async def delete_location(location_id: int):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("DELETE FROM location_criteria WHERE location_id = ?", (location_id,))
    c.execute("DELETE FROM locations WHERE id = ?", (location_id,))
    
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Location not found")
    
    conn.commit()
    conn.close()
    return {"message": "Location deleted"}

# Criteria endpoints
@app.get("/criteria", response_model=List[Criteria])
async def get_criteria():
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM criteria")
    criteria = c.fetchall()
    conn.close()
    
    return [dict(criterion) for criterion in criteria]

@app.post("/criteria", response_model=Criteria)
async def create_criteria(criteria: CriteriaBase):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("INSERT INTO criteria (id, name, weight, type) VALUES (?, ?, ?, ?)",
              (criteria.id, criteria.name, criteria.weight, criteria.type))
    
    conn.commit()
    conn.close()
    
    return criteria

@app.put("/criteria/{criteria_id}", response_model=Criteria)
async def update_criteria(criteria_id: str, criteria: CriteriaBase):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("UPDATE criteria SET id = ?, name = ?, weight = ?, type = ? WHERE id = ?",
              (criteria.id, criteria.name, criteria.weight, criteria.type, criteria_id))
    
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Criteria not found")
    
    if criteria_id != criteria.id:
        c.execute("UPDATE location_criteria SET criteria_id = ? WHERE criteria_id = ?",
                  (criteria.id, criteria_id))
    
    conn.commit()
    conn.close()
    
    return criteria

@app.delete("/criteria/{criteria_id}")
async def delete_criteria(criteria_id: str):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("DELETE FROM location_criteria WHERE criteria_id = ?", (criteria_id,))
    c.execute("DELETE FROM criteria WHERE id = ?", (criteria_id,))
    
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Criteria not found")
    
    conn.commit()
    conn.close()
    return {"message": "Criteria deleted"}

# Analysis endpoints
@app.get("/analysis/saw")
async def calculate_saw():
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM locations")
    locations = c.fetchall()
    
    c.execute("SELECT * FROM criteria")
    criteria = c.fetchall()
    
    if not locations or not criteria:
        conn.close()
        return []
    
    normalized_matrix = {}
    for criterion in criteria:
        c.execute("SELECT location_id, value FROM location_criteria WHERE criteria_id = ?",
                 (criterion['id'],))
        values = [row['value'] for row in c.fetchall()]
        
        if not values:
            continue
            
        max_value = max(values)
        min_value = min(values)
        
        for loc in locations:
            c.execute("SELECT value FROM location_criteria WHERE location_id = ? AND criteria_id = ?",
                     (loc['id'], criterion['id']))
            value = c.fetchone()
            value = value['value'] if value else 0
            
            if loc['id'] not in normalized_matrix:
                normalized_matrix[loc['id']] = {}
                
            if criterion['type'] == "benefit":
                normalized_matrix[loc['id']][criterion['id']] = value / max_value if max_value > 0 else 0
            else:
                normalized_matrix[loc['id']][criterion['id']] = min_value / value if min_value > 0 and value > 0 else 0
    
    results = []
    for loc in locations:
        score = sum(criterion['weight'] * (normalized_matrix[loc['id']].get(criterion['id'], 0))
                   for criterion in criteria)
        results.append({
            "location": loc['name'],
            "score": round(score, 4),
            "details": normalized_matrix[loc['id']]
        })
    
    conn.close()
    return sorted(results, key=lambda x: x['score'], reverse=True)

@app.get("/analysis/wp")
async def calculate_wp():
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM locations")
    locations = c.fetchall()
    
    c.execute("SELECT * FROM criteria")
    criteria = c.fetchall()
    
    if not locations or not criteria:
        conn.close()
        return []
    
    s_values = []
    for loc in locations:
        s = 1
        for criterion in criteria:
            c.execute("SELECT value FROM location_criteria WHERE location_id = ? AND criteria_id = ?",
                     (loc['id'], criterion['id']))
            value = c.fetchone()
            value = value['value'] if value else 0
            
            if value == 0:
                continue
                
            weight = -criterion['weight'] if criterion['type'] == "cost" else criterion['weight']
            s *= math.pow(value, weight)
        
        s_values.append({"location": loc['name'], "s": s})
    
    total_s = sum(item['s'] for item in s_values)
    
    results = [{
        "location": item['location'],
        "score": round(item['s'] / total_s, 4) if total_s > 0 else 0,
        "s": item['s']
    } for item in s_values]
    
    conn.close()
    return sorted(results, key=lambda x: x['score'], reverse=True)
