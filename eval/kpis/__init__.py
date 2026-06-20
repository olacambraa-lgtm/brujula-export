"""Scorers por KPI de la capa frontend (Fase 2).

Cada módulo expone `check(bundle, con) -> dict` (forma de eval.kpis._util.kpi) y
consume el bundle de evidencias de eval/frontend.py. eval/scorecard.py los importa
y fusiona, sustituyendo los placeholders `na`.
"""
