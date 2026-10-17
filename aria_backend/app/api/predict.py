import time

from fastapi import APIRouter, Query, Request, Response

router = APIRouter()


@router.get("/predict")
async def predict(request: Request, response: Response, prefix: str = Query("", max_length=2000)):
    started = time.perf_counter()
    suggestions = request.app.state.predictor.suggest(prefix)
    response.headers["X-Prediction-Ms"] = f"{(time.perf_counter() - started) * 1000:.3f}"
    response.headers["Cache-Control"] = "no-store"
    return {"prefix": prefix, "suggestions": suggestions}
