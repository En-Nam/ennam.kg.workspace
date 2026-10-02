"""Employee hourly wage (new column) — needed for labor cost / labor % (RET-LABOR-001)."""
from . import config as C
from .ctx import Ctx


def add_hourly_wage(ctx: Ctx) -> None:
    table = ctx.t["employees"]
    if "hourly_wage" not in table.columns:
        table.columns.append("hourly_wage")
    for row in table.rows:
        base = C.WAGE_BY_ROLE[row["role"]]
        row["hourly_wage"] = f"{base * (1 + ctx.rng.uniform(-0.05, 0.05)):.2f}"
