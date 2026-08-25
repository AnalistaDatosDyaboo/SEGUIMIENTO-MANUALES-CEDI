"""
Limpieza y enriquecimiento temporal de las solicitudes de citas de entrega
de "auxiliares" (unidades con novedad) que confeccionistas y manuales traen
al CEDI para reproceso.

Fuente: hoja "SolicitudesCitas" (ver `cargar_solicitudes_citas.py`). Esa hoja
registra únicamente eventos donde ya hubo una novedad al momento de la
entrega: no incluye las entregas sin problema, así que por sí sola no sirve
para calcular una tasa sobre el 100% de lo que cada proveedor entrega. Por
eso `procesamiento_entregas.py` cruza el DataFrame que produce este módulo
con el universo completo de entregas (con y sin novedad) para calcular la
tasa real de entregas con novedad.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from cargar_solicitudes_citas import cargar_solicitudes_citas

BASE_DIR = Path(__file__).resolve().parent.parent
VARIABLE_CREDENCIALES_JSON = "KEY_API_GOOGLE_SHEETS_DRIVE"
VARIABLE_RUTA_CREDENCIALES = "GOOGLE_APPLICATION_CREDENTIALS"

COLUMNAS_RENOMBRADAS = {
    "Fecha": "fecha",
    "Nombre proveedor": "proveedor",
    "Numero de OP": "numero_op",
    "Referencia ": "referencia",
    "Cantidad": "cantidad_op",
    "Novedad": "causa",
    "Cantidad novedad": "cantidad_reproceso",
    "Observaciones": "observaciones",
}

GRANULARIDADES = {
    "Día": "D",
    "Semana": "W",
    "Mes": "M",
    "Trimestre": "Q",
    "Año": "Y",
}


def preparar_credenciales_google() -> None:
    """Si `KEY_API_GOOGLE_SHEETS_DRIVE` no está definida, la arma a partir del
    archivo apuntado por `GOOGLE_APPLICATION_CREDENTIALS` en `.env`."""
    if os.environ.get(VARIABLE_CREDENCIALES_JSON):
        return

    ruta_credenciales = os.environ.get(VARIABLE_RUTA_CREDENCIALES)
    if not ruta_credenciales:
        raise RuntimeError(
            f'Falta la variable "{VARIABLE_CREDENCIALES_JSON}" o '
            f'"{VARIABLE_RUTA_CREDENCIALES}" en el archivo .env.'
        )

    ruta = Path(ruta_credenciales)
    if not ruta.is_absolute():
        ruta = BASE_DIR / ruta

    try:
        os.environ[VARIABLE_CREDENCIALES_JSON] = ruta.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f'No se encontró el archivo de credenciales en "{ruta}".'
        ) from exc


def cargar_datos_crudos() -> pd.DataFrame:
    """Carga la hoja de solicitudes de citas ya con las credenciales listas."""
    load_dotenv(BASE_DIR / ".env")
    preparar_credenciales_google()
    return cargar_solicitudes_citas()


def limpiar_datos(df: pd.DataFrame) -> pd.DataFrame:
    """Tipa, normaliza y enriquece con columnas temporales el DataFrame crudo."""
    if df.empty:
        return df

    df = df.rename(columns=COLUMNAS_RENOMBRADAS).copy()

    for columna in ("proveedor", "causa", "observaciones", "numero_op", "referencia"):
        if columna in df.columns:
            df[columna] = df[columna].astype(str).str.strip()

    df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y", errors="coerce")
    df["cantidad_op"] = pd.to_numeric(df["cantidad_op"], errors="coerce")
    df["cantidad_reproceso"] = pd.to_numeric(df["cantidad_reproceso"], errors="coerce")

    df = df.dropna(subset=["fecha"])
    df = df[(df["proveedor"] != "") & (df["causa"] != "")]

    # Una cantidad base solo es confiable para calcular la tasa si existe,
    # es positiva y no es menor que las unidades con novedad reportadas.
    df["cantidad_op_valida"] = (
        df["cantidad_op"].notna()
        & (df["cantidad_op"] > 0)
        & df["cantidad_reproceso"].notna()
        & (df["cantidad_reproceso"] <= df["cantidad_op"])
    )
    df["cantidad_op_para_tasa"] = df["cantidad_op"].where(df["cantidad_op_valida"])
    df["cantidad_reproceso"] = df["cantidad_reproceso"].fillna(0)

    df["anio"] = df["fecha"].dt.year

    return df.reset_index(drop=True)


def _etiqueta_periodo(periodo_inicio: pd.Timestamp, granularidad: str) -> str:
    if granularidad == "Día":
        return periodo_inicio.strftime("%d/%m/%Y")
    if granularidad == "Semana":
        iso = periodo_inicio.isocalendar()
        return f"{iso.year}-S{iso.week:02d}"
    if granularidad == "Mes":
        return periodo_inicio.strftime("%Y-%m")
    if granularidad == "Trimestre":
        return f"{periodo_inicio.year}-T{((periodo_inicio.month - 1) // 3) + 1}"
    return str(periodo_inicio.year)
