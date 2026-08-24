"""
Dashboard interactivo de novedades en la entrega de "auxiliares" (unidades
con problema) que confeccionistas y manuales traen al CEDI para reproceso.

Ejecutar con: uv run streamlit run src/dashboard_novedades.py
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from procesamiento_novedades import (
    GRANULARIDADES,
    VARIABLE_CREDENCIALES_JSON,
    cargar_datos_crudos,
    limpiar_datos,
    resumen_por_causa,
    resumen_por_periodo,
    resumen_por_proveedor,
)

st.set_page_config(page_title="Novedades de entrega — CEDI", layout="wide", page_icon="🧵")


def _preparar_secretos_streamlit_cloud() -> None:
    """En Streamlit Community Cloud las credenciales se configuran como
    "Secrets" (st.secrets), que no se inyectan solas en os.environ. Si no
    hay variable de entorno pero sí existe el secreto, la copiamos.

    Localmente no suele existir `secrets.toml`; en ese caso `st.secrets`
    lanza `StreamlitSecretNotFoundError`, que tratamos como "no hay
    secreto configurado" para seguir usando el `.env` local sin problema.
    """
    if os.environ.get(VARIABLE_CREDENCIALES_JSON):
        return
    try:
        hay_secreto = VARIABLE_CREDENCIALES_JSON in st.secrets
    except StreamlitSecretNotFoundError:
        return
    if hay_secreto:
        os.environ[VARIABLE_CREDENCIALES_JSON] = st.secrets[VARIABLE_CREDENCIALES_JSON]

COLUMNAS_RESUMEN = {
    "proveedor": "Manual / confeccionista",
    "causa": "Causa",
    "cantidad_reproceso": "Unidades en reproceso",
    "cantidad_op_valida": "Unidades base (válidas)",
    "tasa_reproceso": "Tasa de reproceso (%)",
    "solicitudes": "Solicitudes",
}


@st.cache_data(ttl=600, show_spinner="Cargando solicitudes de citas desde Google Sheets...")
def _obtener_datos() -> pd.DataFrame:
    _preparar_secretos_streamlit_cloud()
    df_crudo = cargar_datos_crudos()
    return limpiar_datos(df_crudo)


def _formatear_tasa(valor: float) -> str:
    return "s/d" if pd.isna(valor) else f"{valor:.1f}%"


def _calcular_rango_defecto(atajo: str, fecha_min, fecha_max, hoy: pd.Timestamp):
    if atajo == "Año actual":
        return (max(fecha_min, hoy.replace(month=1, day=1).date()), fecha_max)
    if atajo == "Mes actual":
        return (max(fecha_min, hoy.replace(day=1).date()), fecha_max)
    if atajo == "Semana actual":
        inicio_semana = (hoy - pd.Timedelta(days=hoy.weekday())).date()
        return (max(fecha_min, inicio_semana), fecha_max)
    return (fecha_min, fecha_max)


def _grafico_evolucion(df_periodo: pd.DataFrame, granularidad: str, titulo: str | None = None):
    fig = px.line(
        df_periodo,
        x="periodo_etiqueta",
        y="tasa_reproceso",
        markers=True,
        labels={"periodo_etiqueta": granularidad, "tasa_reproceso": "Tasa de reproceso (%)"},
        title=titulo,
    )
    fig.update_traces(hovertemplate="%{x}<br>Tasa: %{y:.1f}%<extra></extra>")
    fig.update_layout(yaxis_ticksuffix="%")
    return fig


def _grafico_barras_unidades(df_periodo: pd.DataFrame, granularidad: str, titulo: str | None = None):
    fig = px.bar(
        df_periodo,
        x="periodo_etiqueta",
        y="cantidad_reproceso",
        labels={"periodo_etiqueta": granularidad, "cantidad_reproceso": "Unidades en reproceso"},
        title=titulo,
    )
    return fig


def _grafico_ranking(df_resumen: pd.DataFrame, columna: str, valores: str, etiqueta_valores: str, titulo: str):
    datos = df_resumen.dropna(subset=[valores]).sort_values(valores, ascending=False).head(15)
    fig = px.bar(
        datos.sort_values(valores),
        x=valores,
        y=columna,
        orientation="h",
        labels={valores: etiqueta_valores, columna: ""},
        title=titulo,
    )
    if valores == "tasa_reproceso":
        fig.update_layout(xaxis_ticksuffix="%")
    return fig


def main() -> None:
    st.title("🧵 Novedades en la entrega de auxiliares")
    st.caption(
        "Reproceso reportado por confeccionistas y manuales al momento de la entrega "
        "(fuente: hoja *SolicitudesCitas*)."
    )

    try:
        df = _obtener_datos()
    except (RuntimeError, FileNotFoundError) as exc:
        st.error(f"No se pudieron cargar los datos: {exc}")
        st.stop()
        return

    if df.empty:
        st.warning("La hoja de solicitudes de citas no tiene registros.")
        st.stop()
        return

    fecha_min, fecha_max = df["fecha"].min().date(), df["fecha"].max().date()
    hoy = pd.Timestamp.today().normalize()

    st.sidebar.header("Filtros")
    atajo = st.sidebar.radio(
        "Rango rápido",
        ["Todo", "Año actual", "Mes actual", "Semana actual", "Personalizado"],
        index=0,
    )
    rango_defecto = _calcular_rango_defecto(atajo, fecha_min, fecha_max, hoy)

    rango_fechas = st.sidebar.date_input(
        "Rango de fechas",
        value=rango_defecto,
        min_value=fecha_min,
        max_value=fecha_max,
    )
    if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
        fecha_desde, fecha_hasta = rango_fechas
    else:
        fecha_desde, fecha_hasta = fecha_min, fecha_max

    proveedores_sel = st.sidebar.multiselect(
        "Manual / confeccionista", sorted(df["proveedor"].unique()), default=[]
    )
    causas_sel = st.sidebar.multiselect(
        "Causa de novedad", sorted(df["causa"].unique()), default=[]
    )
    granularidad = st.sidebar.radio("Agrupar evolución por", list(GRANULARIDADES.keys()), index=1)

    mascara = (df["fecha"].dt.date >= fecha_desde) & (df["fecha"].dt.date <= fecha_hasta)
    if proveedores_sel:
        mascara &= df["proveedor"].isin(proveedores_sel)
    if causas_sel:
        mascara &= df["causa"].isin(causas_sel)
    df_filtrado = df.loc[mascara]

    if df_filtrado.empty:
        st.warning("No hay registros para los filtros seleccionados.")
        st.stop()
        return

    total_reproceso = df_filtrado["cantidad_reproceso"].sum()
    total_op_valida = df_filtrado["cantidad_op_para_tasa"].sum()
    tasa_general = (total_reproceso / total_op_valida * 100) if total_op_valida else float("nan")
    n_manuales = df_filtrado["proveedor"].nunique()
    n_solicitudes = len(df_filtrado)
    registros_sin_base = int((~df_filtrado["cantidad_op_valida"]).sum())

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Unidades en reproceso (auxiliares)", f"{total_reproceso:,.0f}")
    col2.metric("Tasa de reproceso general", _formatear_tasa(tasa_general))
    col3.metric("Manuales / confeccionistas", n_manuales)
    col4.metric("Solicitudes con novedad", n_solicitudes)
    col5.metric("Sin cantidad base válida", registros_sin_base)

    with st.expander("ℹ️ Cómo se calcula la tasa de reproceso"):
        st.markdown(
            "La hoja de solicitudes solo registra citas de entrega en las que **ya hubo "
            "una novedad**; no incluye las entregas sin problema. Por eso la tasa se "
            "calcula como `unidades con novedad / unidades de la OP en la que se detectó "
            "la novedad`, sumadas en el periodo o grupo seleccionado: es el porcentaje de "
            "esa OP puntual que llegó con problema, no un porcentaje sobre el 100% de todo "
            "lo que cada proveedor despacha.\n\n"
            f"En el rango filtrado, **{registros_sin_base} de {n_solicitudes}** solicitudes "
            "no tienen una cantidad base válida (vacía, en cero o menor a la cantidad con "
            "novedad) y se excluyen del cálculo de la tasa, aunque sus unidades sí se "
            "cuentan en el total de auxiliares."
        )

    st.divider()

    tab_evolucion, tab_manuales, tab_causas, tab_detalle = st.tabs(
        ["📈 Evolución", "🏭 Manuales", "🔎 Causas", "🕵️ Detalle por manual/causa"]
    )

    with tab_evolucion:
        st.subheader(f"Evolución de la tasa de reproceso — {granularidad.lower()}")
        evolucion = resumen_por_periodo(df_filtrado, granularidad)
        st.plotly_chart(_grafico_evolucion(evolucion, granularidad), width="stretch")
        st.plotly_chart(_grafico_barras_unidades(evolucion, granularidad), width="stretch")

    with tab_manuales:
        st.subheader("Ranking de manuales / confeccionistas")
        resumen_prov = resumen_por_proveedor(df_filtrado)

        col_izq, col_der = st.columns(2)
        with col_izq:
            st.plotly_chart(
                _grafico_ranking(
                    resumen_prov, "proveedor", "cantidad_reproceso",
                    "Unidades en reproceso", "Quién trajo más auxiliares (unidades)",
                ),
                width="stretch",
            )
        with col_der:
            st.plotly_chart(
                _grafico_ranking(
                    resumen_prov, "proveedor", "tasa_reproceso",
                    "Tasa de reproceso (%)", "Mayor tasa de reproceso (%)",
                ),
                width="stretch",
            )

        st.dataframe(
            resumen_prov.rename(columns=COLUMNAS_RESUMEN),
            width="stretch",
            hide_index=True,
        )

    with tab_causas:
        st.subheader("Causas de novedad")
        resumen_causa = resumen_por_causa(df_filtrado)

        col_izq, col_der = st.columns(2)
        with col_izq:
            fig_pie = px.pie(
                resumen_causa,
                names="causa",
                values="cantidad_reproceso",
                title="Distribución de auxiliares por causa",
                hole=0.4,
            )
            st.plotly_chart(fig_pie, width="stretch")
        with col_der:
            st.plotly_chart(
                _grafico_ranking(
                    resumen_causa, "causa", "cantidad_reproceso",
                    "Unidades en reproceso", "Causa que más auxiliares trajo",
                ),
                width="stretch",
            )

        st.dataframe(
            resumen_causa.rename(columns=COLUMNAS_RESUMEN),
            width="stretch",
            hide_index=True,
        )

    with tab_detalle:
        st.subheader("Comportamiento en el tiempo de un manual o una causa")
        st.caption(
            "Útil para, tras ver quién o qué más pegó arriba, revisar cómo evolucionó "
            "específicamente esa manual o esa causa durante el periodo filtrado."
        )
        modo = st.radio("Analizar por", ["Manual / confeccionista", "Causa"], horizontal=True)
        columna = "proveedor" if modo == "Manual / confeccionista" else "causa"
        columna_otro = "causa" if columna == "proveedor" else "proveedor"
        etiqueta_otro = "Causas" if columna_otro == "causa" else "Manuales / confeccionistas"

        resumen_base = resumen_por_proveedor(df_filtrado) if columna == "proveedor" else resumen_por_causa(df_filtrado)
        opciones = resumen_base[columna].tolist()

        if not opciones:
            st.info("No hay datos para detallar con los filtros actuales.")
        else:
            seleccion = st.selectbox("Selecciona", opciones)
            df_seleccion = df_filtrado[df_filtrado[columna] == seleccion]

            evolucion_sel = resumen_por_periodo(df_seleccion, granularidad)
            st.plotly_chart(
                _grafico_evolucion(evolucion_sel, granularidad, f"Evolución de la tasa de reproceso — {seleccion}"),
                width="stretch",
            )
            st.plotly_chart(
                _grafico_barras_unidades(evolucion_sel, granularidad, f"Unidades en reproceso por periodo — {seleccion}"),
                width="stretch",
            )

            resumen_otro = resumen_por_causa(df_seleccion) if columna_otro == "causa" else resumen_por_proveedor(df_seleccion)
            st.plotly_chart(
                _grafico_ranking(
                    resumen_otro, columna_otro, "cantidad_reproceso",
                    "Unidades en reproceso", f"{etiqueta_otro} involucrados en {seleccion}",
                ),
                width="stretch",
            )

    with st.expander("📄 Datos filtrados"):
        st.dataframe(df_filtrado, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
