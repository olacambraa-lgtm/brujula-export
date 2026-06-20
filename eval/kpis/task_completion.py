"""Scorer del KPI task_completion — Task Completion Rate (capa Usabilidad).

Mide el porcentaje de flujos de usuario completados sin errores:
- Búsqueda y apertura del producto
- Selección de país destino
- Visualización de gráficas (monthly, yearly, seasonality, provinces)
- Generación y renderizado del informe

Para cada producto (taric) en la evidencia, comprueba que todos los pasos
estén marcados como completados (completed=True en el paso). El score es
el porcentaje de productos donde completed=true, sobre el total evaluado.
"""

from eval.kpis._util import kpi, status_from, pct


def check(bundle, con):
    """
    Args:
        bundle: dict con evidencias capturadas en Chrome headless.
                bundle['task_completion'] = [{taric, steps:{...}, completed}, ...]
        con: conexión DuckDB (no se usa aquí, requerida por interfaz del scorer).

    Returns:
        dict kpi con estructura estándar: id, layer, name, tier, status, score,
        value, target, detail.
    """

    # Ignorar evidencias que tengan clave 'error' (fallaron en captura).
    task_completions = bundle.get("task_completion", [])
    task_completions = [
        tc for tc in task_completions if not isinstance(tc, dict) or "error" not in tc
    ]

    if not task_completions:
        # Sin datos que medir, score None → status "na".
        return kpi(
            "task_completion",
            "Usabilidad",
            "Task Completion Rate",
            "quality",
            score=None,
            value={},
            target={"completion_rate": 1.0},
            detail="Sin datos de task_completion en el bundle.",
        )

    # Contar flujos completados y no completados.
    completed_count = 0
    incomplete_details = {}

    for entry in task_completions:
        taric = entry.get("taric", "?")

        if entry.get("completed") is True:
            completed_count += 1
        else:
            # Producto con flujo incompleto: registra qué pasos fallaron.
            steps = entry.get("steps", {})
            failed_steps = [step for step, ok in steps.items() if ok is not True]
            incomplete_details[taric] = failed_steps

    total_count = len(task_completions)
    completion_rate = completed_count / total_count if total_count else 0.0
    score = round(100 * completion_rate, 1)

    # Construir value con detalles de completitud.
    value = {
        "completed": completed_count,
        "total": total_count,
        "rate": round(completion_rate, 3),
    }

    # Si hay incompletos, incluir cuáles.
    if incomplete_details:
        value["incomplete_products"] = incomplete_details

    detail_msg = f"{completed_count}/{total_count} flujos completados"
    if incomplete_details:
        failed_tcs = ", ".join(incomplete_details.keys())
        detail_msg += f"; productos con pasos fallidos: {failed_tcs}"

    return kpi(
        "task_completion",
        "Usabilidad",
        "Task Completion Rate",
        "quality",
        score=score,
        value=value,
        target={"completion_rate": 1.0},
        detail=detail_msg,
        status=None,  # status_from() se aplica automáticamente en kpi()
    )
