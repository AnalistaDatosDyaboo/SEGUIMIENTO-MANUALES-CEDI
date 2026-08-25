"""
Carga el detalle de citas de entrega ("df_detallecita", en el Google Sheet
"ENTRADAS Y SALIDAS CEDI") y lo cruza con las novedades reportadas
manualmente en la hoja "SolicitudesCitas" (ver `procesamiento_novedades.py`),
para tener el universo completo de entregas -- con y sin novedad -- y así
calcular una tasa de **entregas con novedad** real (entregas con novedad /
entregas totales) en vez de una tasa por unidades calculada solo sobre las
entregas que ya tenían novedad (que es lo único que registra la hoja de
solicitudes por sí sola).

"df_detallecita" es el detalle línea a línea (una fila por referencia/OP
entregada) de cada cita de entrega. Solo las citas en estado "Recibida"
representan una entrega que efectivamente ocurrió: "Cancelada", "Rechazada",
"Programada" y "Sin agendar" no llegaron a entregarse y no cuentan en el
universo de entregas totales.

El cruce con las novedades se hace por (Número de OP, Referencia)
normalizados: la sola "Referencia" se repite muchas veces en
"df_detallecita" (es el código de un estilo, reusado en distintas OP a lo
largo del tiempo), así que no es una clave confiable por sí sola. Cuando el
mismo par OP/Referencia tiene varias citas recibidas (entregas parciales de
la misma OP en distintas fechas), se toma la más cercana en fecha a la
fecha en que se reportó la novedad. Las novedades que no logran cruzar con
ninguna entrega (p. ej. por un número de OP mal digitado en el formulario)
se cuentan aparte y se reportan en la UI como dato de calidad.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cargar_solicitudes_citas import cargar_solicitudes_citas
from procesamiento_novedades import GRANULARIDADES, _etiqueta_periodo

NOMBRE_ARCHIVO_ENTREGAS = "ENTRADAS Y SALIDAS CEDI"
NOMBRE_HOJA_ENTREGAS = "df_detallecita"
ESTADO_ENTREGA_REAL = "Recibida"

COLUMNAS_RENOMBRADAS_ENTREGAS = {
    "Citas_Fecha_Inicio": "fecha",
    "DetallesCita_Manual": "proveedor",
    "DetallesCita_OP": "numero_op",
    "DetallesCita_Referencia": "referencia",
    "DetallesCita_Cantidad": "cantidad_programada",
    "DetallesCita_Cantidad_Recibida": "cantidad_recibida",
    "Citas_Estado": "estado",
}


def cargar_entregas_crudas() -> pd.DataFrame:
    """Carga la hoja "df_detallecita" ya con las credenciales listas."""
    return cargar_solicitudes_citas(
        nombre_archivo=NOMBRE_ARCHIVO_ENTREGAS, nombre_hoja=NOMBRE_HOJA_ENTREGAS
    )


def limpiar_entregas(df: pd.DataFrame) -> pd.DataFrame:
    """Tipa el detalle de citas y lo reduce al universo de entregas reales."""
    if df.empty:
        return df

    df = df.rename(columns=COLUMNAS_RENOMBRADAS_ENTREGAS).copy()

    for columna in ("proveedor", "numero_op", "referencia", "estado"):
        df[columna] = df[columna].astype(str).str.strip()

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["cantidad_programada"] = pd.to_numeric(df["cantidad_programada"], errors="coerce")
    df["cantidad_recibida"] = pd.to_numeric(df["cantidad_recibida"], errors="coerce")

    df = df[df["estado"] == ESTADO_ENTREGA_REAL]
    df = df.dropna(subset=["fecha"])
    df = df[df["proveedor"] != ""]

    df["op_norm"] = df["numero_op"].str.upper()
    df["ref_norm"] = df["referencia"].str.upper()
    df["anio"] = df["fecha"].dt.year

    return df.reset_index(drop=True)


def cruzar_con_novedades(
    df_entregas: pd.DataFrame, df_novedades: pd.DataFrame
) -> tuple[pd.DataFrame, int]:
    """Marca en `df_entregas` cuáles entregas tuvieron una novedad reportada.

    Devuelve el universo de entregas con las columnas `tiene_novedad`,
    `causa` y `cantidad_reproceso` agregadas, y la cantidad de novedades
    reportadas que no se pudieron cruzar con ninguna entrega.
    """
    df_entregas = df_entregas.copy()
    df_entregas["tiene_novedad"] = False
    df_entregas["causa"] = pd.Series(pd.NA, index=df_entregas.index, dtype="object")
    df_entregas["cantidad_reproceso"] = 0.0

    if df_novedades.empty:
        return df_entregas, 0

    df_novedades = df_novedades.copy()
    df_novedades["op_norm"] = df_novedades["numero_op"].astype(str).str.strip().str.upper()
    df_novedades["ref_norm"] = df_novedades["referencia"].astype(str).str.strip().str.upper()

    candidatos_por_clave: dict[tuple[str, str], list[int]] = {}
    for idx, fila in df_entregas.iterrows():
        candidatos_por_clave.setdefault((fila["op_norm"], fila["ref_norm"]), []).append(idx)

    usados: set[int] = set()
    sin_cruce = 0
    for _, novedad in df_novedades.iterrows():
        clave = (novedad["op_norm"], novedad["ref_norm"])
        candidatos = [i for i in candidatos_por_clave.get(clave, []) if i not in usados]
        if not candidatos:
            sin_cruce += 1
            continue

        mejor = min(
            candidatos,
            key=lambda i: abs((df_entregas.at[i, "fecha"] - novedad["fecha"]).days),
        )
        usados.add(mejor)
        df_entregas.at[mejor, "tiene_novedad"] = True
        df_entregas.at[mejor, "causa"] = novedad["causa"]
        df_entregas.at[mejor, "cantidad_reproceso"] = novedad["cantidad_reproceso"]

    return df_entregas, sin_cruce


def construir_universo_entregas(df_novedades: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Punto de entrada: carga, limpia y cruza el universo de entregas."""
    df_crudo = cargar_entregas_crudas()
    df_entregas = limpiar_entregas(df_crudo)
    return cruzar_con_novedades(df_entregas, df_novedades)


def resumen_por_periodo(df_entregas: pd.DataFrame, granularidad: str) -> pd.DataFrame:
    """Serie temporal de entregas totales, con novedad y su tasa (%)."""
    columnas_salida = [
        "periodo_inicio",
        "periodo_etiqueta",
        "entregas_totales",
        "entregas_con_novedad",
        "tasa_entregas_con_novedad",
    ]
    if df_entregas.empty:
        return pd.DataFrame(columns=columnas_salida)

    codigo = GRANULARIDADES[granularidad]
    periodo_inicio = df_entregas["fecha"].dt.to_period(codigo).apply(lambda p: p.start_time)

    agregado = (
        df_entregas.assign(periodo_inicio=periodo_inicio)
        .groupby("periodo_inicio", as_index=False)
        .agg(
            entregas_totales=("tiene_novedad", "size"),
            entregas_con_novedad=("tiene_novedad", "sum"),
        )
        .sort_values("periodo_inicio")
    )
    agregado["periodo_etiqueta"] = agregado["periodo_inicio"].apply(
        lambda t: _etiqueta_periodo(t, granularidad)
    )
    agregado["tasa_entregas_con_novedad"] = (
        agregado["entregas_con_novedad"] / agregado["entregas_totales"] * 100
    ).replace([np.inf, -np.inf], np.nan)
    return agregado.reset_index(drop=True)


def resumen_por_proveedor(df_entregas: pd.DataFrame) -> pd.DataFrame:
    """Entregas totales, con novedad, unidades y tasa (%) por manual/confeccionista."""
    columnas_salida = [
        "proveedor",
        "entregas_totales",
        "entregas_con_novedad",
        "unidades_reproceso",
        "tasa_entregas_con_novedad",
    ]
    if df_entregas.empty:
        return pd.DataFrame(columns=columnas_salida)

    agregado = df_entregas.groupby("proveedor", as_index=False).agg(
        entregas_totales=("tiene_novedad", "size"),
        entregas_con_novedad=("tiene_novedad", "sum"),
        unidades_reproceso=("cantidad_reproceso", "sum"),
    )
    agregado["tasa_entregas_con_novedad"] = (
        agregado["entregas_con_novedad"] / agregado["entregas_totales"] * 100
    ).replace([np.inf, -np.inf], np.nan)
    return agregado.sort_values("entregas_con_novedad", ascending=False).reset_index(drop=True)


def resumen_por_causa(df_entregas: pd.DataFrame) -> pd.DataFrame:
    """Entregas con novedad, unidades y participación (%) sobre el total de
    entregas, por causa. La causa solo existe en entregas con novedad, así
    que su "tasa" se expresa como parte del total de entregas del universo
    recibido, no como una tasa propia de la causa."""
    columnas_salida = [
        "causa",
        "entregas_con_novedad",
        "unidades_reproceso",
        "tasa_sobre_entregas_totales",
    ]
    con_novedad = df_entregas[df_entregas["tiene_novedad"]]
    if con_novedad.empty:
        return pd.DataFrame(columns=columnas_salida)

    total_entregas = len(df_entregas)
    agregado = con_novedad.groupby("causa", as_index=False).agg(
        entregas_con_novedad=("causa", "size"),
        unidades_reproceso=("cantidad_reproceso", "sum"),
    )
    agregado["tasa_sobre_entregas_totales"] = (
        agregado["entregas_con_novedad"] / total_entregas * 100 if total_entregas else np.nan
    )
    return agregado.sort_values("entregas_con_novedad", ascending=False).reset_index(drop=True)
