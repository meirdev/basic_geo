import datetime

import asyncpg
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

PG_DNS = "postgresql://postgres:mysecretpassword@localhost:5432/postgres"

app = FastAPI()


class CreateActivity(BaseModel):
    points: list[tuple[float, float]]
    timestamp: tuple[datetime.datetime, datetime.datetime]


class GetActivity(BaseModel):
    start_date: datetime.datetime
    end_date: datetime.datetime
    total_distance: float


@app.on_event("startup")
async def startup_event():
    app.state.pool = await asyncpg.create_pool(PG_DNS)

    async with app.state.pool.acquire() as con:
        await con.execute(
            """
            CREATE TABLE IF NOT EXISTS public.activities (
                id SERIAL PRIMARY KEY,
                timestamp tsrange,
                geo geometry
            )
            """
        )


@app.get("/tiles/{z}/{x}/{y}.mvt")
async def get_tile(z: int, x: int, y: int):
    query = f"""
    WITH
        bounds AS (
            SELECT ST_TileEnvelope({z}, {x}, {y}) AS geom
        ),
        mvtgeom AS (
            SELECT
                ST_AsMVTGeom(ST_Transform(ST_SetSRID(t.geo, 4326), 3857), bounds.geom) AS geom
            FROM
                public.activities t, bounds
            WHERE
                ST_Intersects(ST_Transform(ST_SetSRID(t.geo, 4326), 3857), bounds.geom)
        )
    SELECT
        ST_AsMVT(mvtgeom.*)
    FROM
        mvtgeom
    """

    async with app.state.pool.acquire() as con:
        content = await con.fetchval(query)

    return Response(bytes(content), media_type="application/vnd.mapbox-vector-tile")


@app.get("/activities")
async def get_activities():
    async with app.state.pool.acquire() as con:
        query = f"""
        SELECT
            ST_Length(ST_SetSRID(t.geo, 4326)::geography) AS total_distance, timestamp
        FROM
            public.activities t
        ORDER BY
            lower(timestamp)
        DESC
        """

        activities = []
        for row in await con.fetch(query):
            activities.append(
                GetActivity(
                    start_date=row["timestamp"].lower,
                    end_date=row["timestamp"].upper,
                    total_distance=row["total_distance"],
                ),
            )
        return activities


@app.post("/activities")
async def add_activity(activity: CreateActivity):
    async with app.state.pool.acquire() as con:
        points = ", ".join([f"{p[0]} {p[1]}" for p in activity.points])

        query = f"""
        INSERT INTO
            public.activities (timestamp, geo)
        VALUES ('[{activity.timestamp[0]}, {activity.timestamp[1]}]', 'LINESTRING({points})')
        """

        await con.execute(query)


@app.get("/")
async def map():
    with open("index.htm") as f:
        return HTMLResponse(f.read())
