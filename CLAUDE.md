# CLAUDE.md

@.agents/rules/01_security.md
@.agents/rules/02_uv_environment.md
@.agents/rules/03_python_code_style.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Idioma

Responde siempre en español en este proyecto, tanto en el chat como en los comentarios explicativos que generes. El código, nombres de variables/funciones y mensajes de commit pueden seguir en inglés según convención del proyecto.

## Project purpose

Data pipeline that pulls sales, inventory, inter-warehouse transfer, and expense data from a Microsoft SQL Server data warehouse (via `pytds`) into pandas DataFrames, in order to build "Estados de Resultados" (income statements) per tienda. `src/estado_resultados.py` composes the four query functions in `src/conexion_sql.py` into a per-store P&L.

## Commands

- Run any script: `uv run python src/<script>.py` — never invoke `python` directly, and never `pip install` (use `uv add <package>` / `uv add --dev <package>` instead).
- Run all commands from the project root (the `ESTADOS DE RESULTADOS` directory).
- Build the P&L and export it to `data/estado_resultados.xlsx`: `uv run python src/estado_resultados.py`.
- There is currently no `src/validar_conexiones.py`, but project convention (see `.claude/rules/02_uv_environment.md`) is to validate DB connectivity/query changes by running it after any change to the data layer — create/update it alongside connection changes.

## Architecture

- `src/conexion_sql.py` is the sole data-access layer. It defines four raw SQL query templates (ventas de tiendas / facturación detalle, inventario final por bodega, movimientos de traslado entre áreas, gastos contables por centro de costos) against SQL Server views (`dbo.vUN_MovimientosFacturacion_Detalle`, `dbo.vUN_SaldosBodegaArticulo_Historico`, `dbo.vAL_MovimientosTraslado_Area`, `dbo.vDY_MovimientoContable_Detalle`), plus wrapper functions (`consultar_ventas_tiendas`, `consultar_inventario_final`, `consultar_movimientos_traslado`, `consultar_gastos_tiendas`) that accept date/period parameters and return `pd.DataFrame` via `ejecutar_consulta`.
- Connections are opened per-call through `obtener_conexion`, which reads DB credentials from `.env` and connects with `pytds.connect`. There is no persistent/pooled connection — every query function opens and closes its own connection.
- `src/config/tiendas.py` holds the tienda reference data: `normalizar_nombre_tienda` (used to reconcile the bodega/centro-de-costos names each source returns under a single "Tienda" key) and `FUENTES_TRASLADOS` (the fuente→tienda/entrada-salida dictionary needed only for traslados, since that view doesn't return a store name directly — see the module docstring for which parts are confirmed vs. assumed from the process transcripts).
- `src/transformaciones/{ventas,inventario,compras,gastos}.py` each tag their query's DataFrame with a `Tienda` column and expose a `resumir_*_por_tienda` function that aggregates it to one row per tienda. `compras.py` covers the traslados-between-tiendas query (treated as compra/devolución at cost). `gastos.py` optionally reclassifies `Cuenta_Codigo` via `data/plan_cuentas_gastos.csv` (a template — replace with the real plan de cuentas) and falls back to the raw account name when that file is absent.
- `src/estado_resultados.py` is the orchestrator: `construir_estado_resultados(fecha_inicio, fecha_fin, periodo, ruta_env)` calls the four query functions, runs them through the transformaciones, and merges the per-tienda summaries into one P&L DataFrame; `exportar_estado_resultados` writes it to `data/`. Cost of sales and store margins are estimated (85% of net revenue, per Contabilidad's manual rule of thumb) rather than a real per-item costing — see the module docstring for what's an estimate vs. a direct query total.

## Critical rules (from `.claude/rules/`, applies to all Claude Code work here)

These are marked `always_on` and must be followed without exception:

1. **Environment variables are secret.** Never read, print, or inline the contents of `.env` in code, chat, or committed files. Credentials must be loaded via `os.getenv()` or `python-dotenv`, never hardcoded. (Note: the existing `cargar_variables_env`/`obtener_conexion` in `conexion_sql.py` reads `.env` manually rather than via `python-dotenv`/`os.getenv` — follow the rule's intent, not this precedent, when touching this code.)
2. **No absolute paths.** Use `pathlib.Path` with `BASE_DIR = Path(__file__).resolve().parent.parent` style relative paths, especially for anything under `data/`.
3. **All reusable code lives in `src/`**, uses type hints on function signatures, and catches specific exceptions (`FileNotFoundError`, `pyodbc.Error`, `pd.errors.EmptyDataError`) rather than bare `except`.
4. **Before modifying critical logic in `src/calculos_nomina.py`** (payroll calculations, if/when it exists), present a plan/summary of the proposed changes first and get explicit confirmation before writing to disk — do not silently edit or overwrite that file.
5. **After any change to the data/connection layer** (`conexion_sql.py` or similar), validate by running `uv run python src/validar_conexiones.py`.
