from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.consumer import start_consumer, stop_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_consumer()
    yield
    stop_consumer()


app = FastAPI(title="Boundr Fine-tune", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "finetune"}
