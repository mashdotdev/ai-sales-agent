from fastapi import FastAPI

from routers import agent, health

app = FastAPI(
    title="AI Sales Employee",
    description="Voice + email AI SDR — shared tools layer for both channels.",
)

app.include_router(health.router)
app.include_router(agent.router)
