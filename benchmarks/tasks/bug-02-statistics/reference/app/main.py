from fastapi import FastAPI
from pydantic import BaseModel

from app.stats import average, median

app = FastAPI()


class Numbers(BaseModel):
    values: list[float]


@app.post("/stats")
def stats(n: Numbers):
    return {"count": len(n.values), "average": average(n.values), "median": median(n.values)}
