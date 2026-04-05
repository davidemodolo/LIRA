"""API routes for plot generation."""

import base64
import io
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/plots", tags=["plots"])

if TYPE_CHECKING:
    import matplotlib.pyplot as plt

try:
    import matplotlib
    import matplotlib.pyplot as plt

    matplotlib.use("Agg")
except ImportError:
    plt = None  # type: ignore[assignment]
    matplotlib = None  # type: ignore[assignment]


class PlotRequest(BaseModel):
    """Plot request parameters."""

    plot_type: str
    title: str
    data: list[dict[str, Any]]
    x_key: str = "x"
    y_key: str = "y"


@router.post("/generate")
async def generate_plot(request: PlotRequest) -> dict[str, str]:
    """Generate a plot and return as base64."""
    if matplotlib is None or plt is None:
        raise HTTPException(status_code=500, detail="matplotlib not available")

    fig, ax = plt.subplots(figsize=(10, 6))

    if request.plot_type == "bar":
        x_vals = [d.get(request.x_key, "") for d in request.data]
        y_vals = [float(d.get(request.y_key, 0)) for d in request.data]
        ax.bar(x_vals, y_vals, color="#4c72b0")
    elif request.plot_type == "line":
        x_vals = [d.get(request.x_key, "") for d in request.data]
        y_vals = [float(d.get(request.y_key, 0)) for d in request.data]
        ax.plot(x_vals, y_vals, marker="o", linestyle="-", color="#4c72b0")
    elif request.plot_type == "pie":
        labels = [d.get(request.x_key, "") for d in request.data]
        sizes = [float(d.get(request.y_key, 0)) for d in request.data]
        ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
        ax.axis("equal")
    elif request.plot_type == "scatter":
        x_vals = [float(d.get(request.x_key, 0)) for d in request.data]
        y_vals = [float(d.get(request.y_key, 0)) for d in request.data]
        ax.scatter(x_vals, y_vals, alpha=0.7)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown plot_type: {request.plot_type}")

    ax.set_title(request.title)
    ax.set_xlabel(request.x_key)
    ax.set_ylabel(request.y_key)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", dpi=100)
    buffer.seek(0)

    img_base64 = base64.b64encode(buffer.read()).decode("utf-8")
    plt.close(fig)

    return {"image": f"data:image/png;base64,{img_base64}"}
