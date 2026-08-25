"""
Dashboard interactivo de novedades en la entrega de "auxiliares" (unidades
con problema) que confeccionistas y manuales traen al CEDI para reproceso.

La tasa mostrada es "entregas con novedad / entregas totales": se cruza el
universo completo de entregas recibidas (hoja "df_detallecita" del Google
Sheet "ENTRADAS Y SALIDAS CEDI") con las novedades reportadas manualmente
(hoja "SolicitudesCitas") para saber, del total de lo que realmente se
entregó, qué porcentaje tuvo un problema — no solo un promedio calculado
sobre las entregas que ya se sabía que tenían novedad.

Ejecutar con: uv run streamlit run src/dashboard_novedades.py
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from procesamiento_entregas import (
    construir_universo_entregas,
    resumen_por_causa,
    resumen_por_periodo,
    resumen_por_proveedor,
)
from procesamiento_novedades import (
    GRANULARIDADES,
    VARIABLE_CREDENCIALES_JSON,
    cargar_datos_crudos,
    limpiar_datos,
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

GRANULARIDAD_SUGERIDA_POR_ATAJO = {
    "Año actual": "Mes",
    "Mes actual": "Día",
    "Semana actual": "Día",
}

COLUMNAS_RESUMEN = {
    "proveedor": "Manual / confeccionista",
    "causa": "Causa",
    "entregas_totales": "Entregas totales",
    "entregas_con_novedad": "Entregas con novedad",
    "unidades_reproceso": "Unidades en reproceso",
    "tasa_entregas_con_novedad": "Tasa de entregas con novedad (%)",
    "tasa_sobre_entregas_totales": "% del total de entregas",
}


@st.cache_data(ttl=600, show_spinner="Cargando solicitudes de citas desde Google Sheets...")
def _obtener_datos() -> pd.DataFrame:
    _preparar_secretos_streamlit_cloud()
    df_crudo = cargar_datos_crudos()
    return limpiar_datos(df_crudo)


@st.cache_data(ttl=600, show_spinner="Cruzando entregas totales con novedades desde Google Sheets...")
def _obtener_universo_entregas(df_novedades: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    _preparar_secretos_streamlit_cloud()
    return construir_universo_entregas(df_novedades)


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
        y="tasa_entregas_con_novedad",
        markers=True,
        labels={"periodo_etiqueta": granularidad, "tasa_entregas_con_novedad": "Tasa de entregas con novedad (%)"},
        title=titulo,
    )
    fig.update_traces(hovertemplate="%{x}<br>Tasa: %{y:.1f}%<extra></extra>")
    fig.update_layout(yaxis_ticksuffix="%")
    return fig


def _grafico_barras_entregas(df_periodo: pd.DataFrame, granularidad: str, titulo: str | None = None):
    fig = px.bar(
        df_periodo,
        x="periodo_etiqueta",
        y="entregas_con_novedad",
        labels={"periodo_etiqueta": granularidad, "entregas_con_novedad": "Entregas con novedad"},
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
    if valores.startswith("tasa"):
        fig.update_layout(xaxis_ticksuffix="%")
    return fig


def main() -> None:
    st.title("🧵 Novedades en la entrega de auxiliares")
    st.caption(
        "Del total de entregas recibidas en el CEDI (hoja *df_detallecita*), qué "
        "porcentaje tuvo una novedad reportada por el confeccionista/manual o por "
        "el CEDI al momento de recibirla (hoja *SolicitudesCitas*)."
    )

    try:
        df_novedades = _obtener_datos()
    except (RuntimeError, FileNotFoundError) as exc:
        st.error(f"No se pudieron cargar las novedades: {exc}")
        st.stop()
        return

    try:
        df_entregas, n_sin_cruce = _obtener_universo_entregas(df_novedades)
    except (RuntimeError, FileNotFoundError) as exc:
        st.error(f"No se pudo cargar el detalle de entregas: {exc}")
        st.stop()
        return

    if df_entregas.empty:
        st.warning("No hay entregas recibidas registradas en la hoja df_detallecita.")
        st.stop()
        return

    fecha_min, fecha_max = df_entregas["fecha"].min().date(), df_entregas["fecha"].max().date()
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
        "Manual / confeccionista", sorted(df_entregas["proveedor"].unique()), default=[]
    )
    causas_sel = st.sidebar.multiselect(
        "Causa de novedad",
        sorted(df_entregas.loc[df_entregas["tiene_novedad"], "causa"].dropna().unique()),
        default=[],
    )
    opciones_granularidad = list(GRANULARIDADES.keys())
    sugerida = GRANULARIDAD_SUGERIDA_POR_ATAJO.get(atajo, "Mes")
    if st.session_state.get("_atajo_anterior") != atajo:
        st.session_state["granularidad"] = sugerida
        st.session_state["_atajo_anterior"] = atajo

    granularidad = st.sidebar.radio(
        "Agrupar evolución por",
        opciones_granularidad,
        key="granularidad",
    )
    if atajo in GRANULARIDAD_SUGERIDA_POR_ATAJO:
        st.sidebar.caption(
            f'📈 Sugerido para "{atajo}": **{sugerida.lower()}** — puedes cambiarlo arriba.'
        )

    mascara = (df_entregas["fecha"].dt.date >= fecha_desde) & (df_entregas["fecha"].dt.date <= fecha_hasta)
    if proveedores_sel:
        mascara &= df_entregas["proveedor"].isin(proveedores_sel)
    df_filtrado = df_entregas.loc[mascara].copy()

    # Filtrar por causa NO elimina las entregas sin novedad: el total de
    # entregas (denominador) se mantiene igual y solo se restringe cuáles
    # entregas cuentan como "con novedad" (numerador) a las causas elegidas.
    if causas_sel:
        df_filtrado["tiene_novedad"] = df_filtrado["tiene_novedad"] & df_filtrado["causa"].isin(causas_sel)

    if df_filtrado.empty:
        st.warning("No hay entregas para los filtros seleccionados.")
        st.stop()
        return

    entregas_totales = len(df_filtrado)
    entregas_con_novedad = int(df_filtrado["tiene_novedad"].sum())
    tasa_general = (entregas_con_novedad / entregas_totales * 100) if entregas_totales else float("nan")
    n_manuales = df_filtrado["proveedor"].nunique()
    unidades_reproceso = df_filtrado.loc[df_filtrado["tiene_novedad"], "cantidad_reproceso"].sum()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Entregas totales", f"{entregas_totales:,.0f}")
    col2.metric("Entregas con novedad", f"{entregas_con_novedad:,.0f}")
    col3.metric("Tasa de entregas con novedad", _formatear_tasa(tasa_general))
    col4.metric("Manuales / confeccionistas", n_manuales)
    col5.metric("Unidades en reproceso (auxiliares)", f"{unidades_reproceso:,.0f}")

    with st.expander("ℹ️ Cómo se calcula la tasa de entregas con novedad"):
        st.markdown(
            "Se cruza el detalle completo de citas de entrega recibidas en el CEDI "
            "(`df_detallecita`) con las novedades reportadas por separado "
            "(`SolicitudesCitas`), emparejando por número de OP y referencia — y, "
            "cuando la misma OP tuvo varias citas, tomando la más cercana en fecha "
            "a la novedad reportada. Así el porcentaje que ves es "
            "`entregas con novedad / entregas totales`, sobre el 100% de lo que "
            "realmente se entregó (no solo sobre las entregas que ya se sabía que "
            "tenían problema).\n\n"
            f"De las {len(df_novedades)} novedades reportadas en total, "
            f"**{n_sin_cruce}** no se pudieron cruzar con ninguna entrega recibida "
            "(por ejemplo, por un número de OP o referencia mal digitado en el "
            "formulario) y por lo tanto no quedan contabilizadas en esta tasa."
        )

    st.divider()

    tab_evolucion, tab_manuales, tab_causas, tab_detalle = st.tabs(
        ["📈 Evolución", "🏭 Manuales", "🔎 Causas", "🕵️ Detalle por manual/causa"]
    )

    with tab_evolucion:
        st.subheader(f"Evolución de la tasa de entregas con novedad — {granularidad.lower()}")
        evolucion = resumen_por_periodo(df_filtrado, granularidad)
        st.plotly_chart(_grafico_evolucion(evolucion, granularidad), width="stretch")
        st.plotly_chart(_grafico_barras_entregas(evolucion, granularidad), width="stretch")

    with tab_manuales:
        st.subheader("Ranking de manuales / confeccionistas")
        resumen_prov = resumen_por_proveedor(df_filtrado)

        col_izq, col_der = st.columns(2)
        with col_izq:
            st.plotly_chart(
                _grafico_ranking(
                    resumen_prov, "proveedor", "tasa_entregas_con_novedad",
                    "Tasa de entregas con novedad (%)", "Mayor tasa de entregas con novedad (%)",
                ),
                width="stretch",
            )
        with col_der:
            st.plotly_chart(
                _grafico_ranking(
                    resumen_prov, "proveedor", "entregas_con_novedad",
                    "Entregas con novedad", "Quién tuvo más entregas con novedad",
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
                values="entregas_con_novedad",
                title="Distribución de entregas con novedad por causa",
                hole=0.4,
            )
            st.plotly_chart(fig_pie, width="stretch")
        with col_der:
            st.plotly_chart(
                _grafico_ranking(
                    resumen_causa, "causa", "tasa_sobre_entregas_totales",
                    "% del total de entregas", "Causas con mayor impacto sobre el total de entregas",
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

        if modo == "Manual / confeccionista":
            resumen_base = resumen_por_proveedor(df_filtrado)
            opciones = resumen_base["proveedor"].tolist()
        else:
            resumen_base = resumen_por_causa(df_filtrado)
            opciones = resumen_base["causa"].tolist()

        if not opciones:
            st.info("No hay datos para detallar con los filtros actuales.")
        else:
            seleccion = st.selectbox("Selecciona", opciones)

            if modo == "Manual / confeccionista":
                # Se conserva el universo completo de ese proveedor (con y sin
                # novedad) para que la tasa siga siendo "entregas con novedad
                # de este proveedor / entregas totales de este proveedor".
                df_seleccion = df_filtrado[df_filtrado["proveedor"] == seleccion].copy()
                resumen_otro = resumen_por_causa(df_seleccion)
                etiqueta_otro, columna_otro = "Causas involucradas", "causa"
            else:
                # Para una causa no hay un "total de entregas de esa causa":
                # se mantiene el universo completo filtrado y solo se cuentan
                # como "con novedad" las entregas de esa causa específica, así
                # la tasa muestra qué % de TODAS las entregas tuvo esa causa.
                df_seleccion = df_filtrado.copy()
                df_seleccion["tiene_novedad"] = df_seleccion["tiene_novedad"] & (df_seleccion["causa"] == seleccion)
                resumen_otro = (
                    df_filtrado[df_filtrado["causa"] == seleccion]
                    .groupby("proveedor", as_index=False)
                    .size()
                    .rename(columns={"size": "entregas_con_novedad"})
                    .sort_values("entregas_con_novedad", ascending=False)
                )
                etiqueta_otro, columna_otro = "Manuales / confeccionistas involucrados", "proveedor"

            evolucion_sel = resumen_por_periodo(df_seleccion, granularidad)
            st.plotly_chart(
                _grafico_evolucion(
                    evolucion_sel, granularidad,
                    f"Evolución de la tasa de entregas con novedad — {seleccion}",
                ),
                width="stretch",
            )
            st.plotly_chart(
                _grafico_barras_entregas(
                    evolucion_sel, granularidad, f"Entregas con novedad por periodo — {seleccion}",
                ),
                width="stretch",
            )

            st.plotly_chart(
                _grafico_ranking(
                    resumen_otro, columna_otro, "entregas_con_novedad",
                    "Entregas con novedad", f"{etiqueta_otro} en {seleccion}",
                ),
                width="stretch",
            )

    with st.expander("📄 Entregas filtradas"):
        st.dataframe(
            df_filtrado[
                [
                    "fecha", "proveedor", "numero_op", "referencia",
                    "cantidad_programada", "cantidad_recibida",
                    "tiene_novedad", "causa", "cantidad_reproceso",
                ]
            ],
            width="stretch",
            hide_index=True,
        )


if __name__ == "__main__":
    main()
