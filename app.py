"""Dashboard Analítico de Tesorería.

Aplicación Streamlit de un solo archivo: login con perfiles, filtros globales,
filtrado cruzado nativo (Plotly + ``on_select``), KPIs, tendencia por
regresión lineal, matriz de variación MoM/YoY y un asistente analítico con
motor de lenguaje natural local (opcionalmente apoyado por un LLM).

Ejecución:  streamlit run app.py
"""
from __future__ import annotations

import difflib
import hashlib
import hmac
import html as _html
import inspect
import io
import json
import os
import re
import time
import unicodedata
import urllib.request
from dataclasses import dataclass, field, replace
from string import Template

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 1. CONSTANTES Y PALETA CORPORATIVA
# =============================================================================
APP_TITULO = "Dashboard Analítico de Tesorería"
LIMITE_BASICO_S = 60
CLAVES = {
    "Básico": os.environ.get("DASH_CLAVE_BASICO", "basico123"),
    "Premium": os.environ.get("DASH_CLAVE_PREMIUM", "premium123"),
}
MODELO_LLM = os.environ.get("ASISTENTE_LLM_MODELO", "claude-sonnet-5-5")

NAVY = "#0B1F33"
NAVY_2 = "#14304A"
INK = "#1B2A3A"
MUTED = "#566678"
BLUE = "#1F618D"
BLUE_SOFT = "#D4E6F1"
SLATE = "#34495E"
GOLD = "#FEE715"
BG = "#F2F5F9"
BORDE = "#D9E1EA"
SUBE = "#B3261E"   # gasto que sube  -> rojo (contraste 6.5:1 sobre blanco)
BAJA = "#1B7A3A"   # gasto que baja  -> verde (contraste 5.6:1 sobre blanco)
FUENTE = "Inter, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
PLOT_CFG = {"displayModeBar": False}

MESES_LARGO = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo",
    6: "junio", 7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre",
    11: "noviembre", 12: "diciembre",
}
MESES_ABR = {k: v[:3] for k, v in MESES_LARGO.items()}
COL_FECHA = ("Fe-contab-", "Fe/contab/", "Fe.contab.", "Fe-contab")
SIN_DESCRIPCION = "(Sin descripción)"
NAT_GASTO = "Gasto"
NAT_MENOR = "Menor gasto / Ingreso"
OPCIONES_NAT = {
    "Todo (valor absoluto)": None,
    "Solo gasto": NAT_GASTO,
    "Solo menor gasto / ingreso": NAT_MENOR,
}

# Alias de entidades: el campo origen viene truncado a 20 caracteres.
ALIAS_ENTIDAD = {
    "BANCOLOMBIA S A": "Bancolombia",
    "BANCOLOMBIA PANAMA S": "Bancolombia Panamá",
    "VALORES BANCOLOMBIA": "Valores Bancolombia",
    "BANCO BILBAO VIZCAYA": "BBVA Colombia",
    "BANCO DAVIVIENDA S A": "Davivienda",
    "BANCO DAVIBANK S A": "Davibank",
    "BANCO DE OCCIDENTE": "Banco de Occidente",
    "BANCO COMERCIAL AV V": "Banco AV Villas",
    "BANCO DE BOGOTA PANA": "Banco de Bogotá Panamá",
    "BANCO DE BOGOTA": "Banco de Bogotá",
    "BANCO GNB SUDAMERIS": "GNB Sudameris",
    "GNB SUDAMERIS": "GNB Sudameris",
    "BANCO AGRARIO DE COL": "Banco Agrario",
    "BANCO CAJA SOCIAL S": "Banco Caja Social",
    "BANCO ITAU COLOMBIA": "Itaú",
    "ITAU COLOMBIA S A": "Itaú",
    "FONDO DE INVERSION C": "Fondo de Inversión Colectiva",
}


# =============================================================================
# 2. FORMATO NUMÉRICO (estilo Power BI, localización es-CO)
# =============================================================================
def _num(valor: float, dec: int = 1) -> str:
    """Formatea con punto de miles y coma decimal."""
    txt = f"{valor:,.{dec}f}"
    return txt.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt(valor: float) -> str:
    """Abrevia como Power BI: ``1,2 mil M`` (miles de millones), ``309,1 M``."""
    if valor is None or pd.isna(valor) or valor == 0:
        return "0"
    a, signo = abs(float(valor)), "-" if valor < 0 else ""
    if a >= 1e12:
        return f"{signo}{_num(a / 1e12)} B"
    if a >= 1e9:
        return f"{signo}{_num(a / 1e9)} mil M"
    if a >= 1e6:
        return f"{signo}{_num(a / 1e6)} M"
    return f"{signo}{_num(a, 0)}"


def money(valor: float) -> str:
    """Moneda para Markdown (escapa ``$`` para evitar LaTeX)."""
    signo = "-" if valor < 0 else ""
    return f"{signo}\\${fmt(abs(valor))}"


def money_html(valor: float) -> str:
    signo = "-" if valor < 0 else ""
    return f"{signo}&#36;{fmt(abs(valor))}"


def cop(valor: float) -> str:
    """Valor completo para tablas: ``$ 1.234.567``."""
    if pd.isna(valor):
        return "—"
    return f"$ {_num(valor, 0)}"


def pct_txt(valor: float, signo: bool = False) -> str:
    if pd.isna(valor) or np.isinf(valor):
        return "—"
    return (f"{valor:+.1f}%" if signo else f"{valor:.1f}%").replace(".", ",")


def etiqueta_periodo(periodo: str) -> str:
    """'2026-03' -> 'mar 2026'."""
    return f"{MESES_ABR[int(periodo[5:7])]} {periodo[:4]}"


def esc(texto: object) -> str:
    return _html.escape(str(texto))


# =============================================================================
# 3. ETL Y MODELO DE DATOS (CACHÉ)
# =============================================================================
def normalizar(texto: object) -> str:
    """Minúsculas, sin tildes ni signos: base del motor de lenguaje."""
    t = unicodedata.normalize("NFKD", str(texto).lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[¿?¡!,;:\"'()\[\]/\\]", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def limpiar_entidad(serie: pd.Series) -> pd.Series:
    crudo = serie.fillna("Sin entidad").astype(str).str.strip()
    clave = crudo.map(lambda x: re.sub(r"\s+", " ", re.sub(r"[.,]", " ", x)).strip())
    clave = clave.str.upper().map(
        lambda x: unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode())
    bonito = crudo.str.title()
    bonito = bonito.str.replace(r"\bS\.?A\.?S\b\.?", "S.A.S", regex=True)
    bonito = bonito.str.replace(r"\bSas\b", "S.A.S", regex=True)
    return pd.Series(
        [ALIAS_ENTIDAD.get(k, b) for k, b in zip(clave, bonito)], index=serie.index)


def limpiar_concepto(serie: pd.Series) -> pd.Series:
    """Agrupa descripciones equivalentes quitando números de factura/crédito."""
    t = serie.fillna("").astype(str).str.upper().str.strip()
    t = t.str.replace(r"\S*\d\S*", " ", regex=True)
    t = t.str.replace(r"\b(?:N[°º]|NRO\.?|NO\.)(?=\s|$)", " ", regex=True)
    t = t.str.replace(r"[\s\-–—:/#.,%]+$", "", regex=True)
    t = t.str.replace(r"^[\s\-–—:/#.,%]+", "", regex=True)
    t = t.str.replace(r"\s+", " ", regex=True).str.strip()
    return t.where(t != "", SIN_DESCRIPCION)


def preparar_datos(crudo: pd.DataFrame) -> pd.DataFrame:
    """Normaliza el Excel contable al modelo interno del tablero."""
    df = crudo.copy()
    df.columns = [str(c).strip() for c in df.columns]
    col_fecha = next((c for c in COL_FECHA if c in df.columns), None)
    col_imp = next((c for c in ("Importe_Graficar", "Importe en ML")
                    if c in df.columns), None)
    if col_fecha is None or col_imp is None:
        raise ValueError(
            "No se encontró la columna de fecha contable (Fe-contab-) o de "
            "importe (Importe_Graficar / Importe en ML).")

    out = pd.DataFrame(index=df.index)
    out["Fecha"] = pd.to_datetime(df[col_fecha], errors="coerce")
    neto = pd.to_numeric(
        df["Importe en ML"] if "Importe en ML" in df.columns else df[col_imp],
        errors="coerce")
    out["Importe_Neto"] = neto                      # precisión contable (con signo)
    out["Importe"] = pd.to_numeric(df[col_imp], errors="coerce").abs()  # gráficos
    out["Naturaleza"] = np.where(neto < 0, NAT_MENOR, NAT_GASTO)
    out["Rubro"] = (df["Nombre cuenta"] if "Nombre cuenta" in df.columns
                    else pd.Series("Sin rubro", index=df.index))
    out["Rubro"] = out["Rubro"].fillna("Sin rubro").astype(str).str.strip().str.title()
    out["Tipo"] = (df["Tipo"] if "Tipo" in df.columns
                   else pd.Series("General", index=df.index))
    out["Tipo"] = out["Tipo"].fillna("Sin clasificar").astype(str).str.strip().str.title()
    out["Entidad"] = limpiar_entidad(
        df["Clave referencia 3"] if "Clave referencia 3" in df.columns
        else pd.Series(np.nan, index=df.index))
    out["Concepto"] = limpiar_concepto(
        df["Texto"] if "Texto" in df.columns else pd.Series("", index=df.index))

    out = out.dropna(subset=["Fecha", "Importe"]).reset_index(drop=True)
    out["Año"] = out["Fecha"].dt.year.astype(int)
    out["Mes"] = out["Fecha"].dt.month.astype(int)
    out["Periodo"] = out["Fecha"].dt.strftime("%Y-%m")
    return out


@st.cache_data(show_spinner=False)
def cargar_datos(huella: str, _contenido: bytes) -> pd.DataFrame:
    """Lee y prepara el Excel una sola vez por archivo (``huella`` = hash)."""
    return preparar_datos(pd.read_excel(io.BytesIO(_contenido)))


# =============================================================================
# 4. FILTROS Y ANALÍTICA
# =============================================================================
@dataclass(frozen=True)
class Filtros:
    anios: tuple
    meses: tuple
    tipos: tuple
    naturaleza: str | None = None
    focos: tuple = ()        # rubros seleccionados (filtro cruzado / comparativa)
    focos_ent: tuple = ()    # entidades seleccionadas (filtro cruzado / comparativa)


def filtrar(df: pd.DataFrame, f: Filtros, periodo: bool = True,
            rubro: bool = True, entidad: bool = True) -> pd.DataFrame:
    """Aplica filtros globales; ``rubro``/``entidad`` activan el foco cruzado."""
    mask = df["Tipo"].isin(f.tipos)
    if f.naturaleza:
        mask &= df["Naturaleza"].eq(f.naturaleza)
    if periodo:
        mask &= df["Año"].between(*f.anios) & df["Mes"].isin(f.meses)
    if rubro and f.focos:
        mask &= df["Rubro"].isin(f.focos)
    if entidad and f.focos_ent:
        mask &= df["Entidad"].isin(f.focos_ent)
    return df[mask]


def serie_mensual(df: pd.DataFrame) -> pd.Series:
    return df.groupby("Periodo")["Importe"].sum().sort_index()


def analizar_tendencia(serie: pd.Series) -> dict:
    """Regresión lineal grado 1 (``np.polyfit``) contra umbral del 1,5 %."""
    n = len(serie)
    vacio = dict(estado="Datos insuficientes", pendiente=0.0, pct=0.0, r2=0.0,
                 media=float(serie.mean()) if n else 0.0, color=MUTED)
    if n == 0:
        return vacio
    media = float(serie.mean())
    if n <= 2:
        return {**vacio, "estado": "➡️ Estable"}
    y, x = serie.to_numpy(dtype=float), np.arange(n)
    pend, inter = np.polyfit(x, y, 1)
    ajuste = np.polyval([pend, inter], x)
    ss_tot = float(((y - media) ** 2).sum())
    r2 = 1 - float(((y - ajuste) ** 2).sum()) / ss_tot if ss_tot else 0.0
    umbral = 0.015 * media
    if pend > umbral:
        estado, color = "📈 Alcista", SUBE
    elif pend < -umbral:
        estado, color = "📉 Bajista", BAJA
    else:
        estado, color = "➡️ Estable", NAVY_2
    return dict(estado=estado, pendiente=float(pend), inter=float(inter),
                pct=pend / media * 100 if media else 0.0, r2=r2, media=media,
                color=color)


def variacion_ultimo_mes(serie: pd.Series):
    """Variación del último mes vs. el mes calendario inmediato anterior."""
    if serie.empty:
        return None
    ult = pd.Period(serie.index[-1], freq="M")
    previo = str(ult - 1)
    if previo not in serie.index or serie[previo] == 0:
        return None
    return serie.index[-1], previo, serie.iloc[-1] / serie[previo] - 1


def matriz_variacion(df: pd.DataFrame) -> pd.DataFrame:
    """Importe mensual con variación MoM y YoY sobre meses calendario reales."""
    s = serie_mensual(df)
    if s.empty:
        return pd.DataFrame()
    idx = pd.period_range(s.index.min(), s.index.max(), freq="M").astype(str)
    full = s.reindex(idx)
    out = pd.DataFrame({
        "Periodo": [etiqueta_periodo(p) for p in idx],
        "Importe": full.to_numpy(),
        "Δ vs mes anterior": (full - full.shift(1)).to_numpy(),
        "Var. MoM %": ((full / full.shift(1) - 1) * 100).to_numpy(),
        "Var. YoY %": ((full / full.shift(12) - 1) * 100).to_numpy(),
    })
    out = out.replace([np.inf, -np.inf], np.nan)
    return out.dropna(subset=["Importe"]).iloc[::-1].reset_index(drop=True)


def resumen_rubros(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("Rubro").agg(
        Importe=("Importe", "sum"), Registros=("Importe", "size"),
        Neto=("Importe_Neto", "sum"))
    g["Gasto bruto"] = df[df["Naturaleza"] == NAT_GASTO].groupby("Rubro")["Importe"].sum()
    g["Menor gasto / Ingreso"] = (
        df[df["Naturaleza"] == NAT_MENOR].groupby("Rubro")["Importe"].sum())
    g = g.fillna(0).sort_values("Importe", ascending=False)
    g["% del total"] = g["Importe"] / g["Importe"].sum() * 100 if g["Importe"].sum() else 0
    return g.reset_index()[["Rubro", "Importe", "% del total", "Gasto bruto",
                            "Menor gasto / Ingreso", "Neto", "Registros"]]


# =============================================================================
# 5. FIGURAS PLOTLY (fondos transparentes, sin cuadrícula en Y)
# =============================================================================
def _estilo(fig: go.Figure, alto: int = 360, leyenda: bool = False) -> go.Figure:
    fig.update_layout(
        height=alto, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FUENTE, size=13, color=INK),
        margin=dict(l=10, r=20, t=16, b=10), showlegend=leyenda,
        hoverlabel=dict(bgcolor=NAVY, font=dict(color="#FFFFFF", size=13, family=FUENTE)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right",
                    x=1, title=None, font=dict(color=INK, size=12)),
    )
    return fig


def _eje_monetario(fig: go.Figure, maximo: float, n: int = 4) -> None:
    ticks = [maximo * i / n for i in range(n + 1)]
    fig.update_yaxes(showgrid=False, zeroline=False, tickvals=ticks,
                     ticktext=[fmt(t) for t in ticks],
                     tickfont=dict(color=MUTED, size=11))


def _eje_x_periodos(fig: go.Figure, n: int) -> None:
    fig.update_xaxes(showgrid=True, gridcolor="#E6ECF2", zeroline=False,
                     tickangle=-45 if n > 10 else 0, type="category",
                     tickfont=dict(color=INK, size=11), linecolor=BORDE)


def _etiquetas_clave(valores: list) -> list:
    """Muestra etiqueta en todos los puntos si son pocos; si no, máx/mín/último."""
    n = len(valores)
    if n <= 12:
        return [fmt(v) for v in valores]
    idx = {int(np.argmax(valores)), int(np.argmin(valores)), n - 1}
    return [fmt(v) if i in idx else "" for i, v in enumerate(valores)]


def fig_evolucion(serie: pd.Series, tend: dict) -> go.Figure:
    x = [etiqueta_periodo(p) for p in serie.index]
    y = serie.to_numpy(dtype=float)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, name="Importe mensual", mode="lines+markers+text",
        text=_etiquetas_clave(list(y)), textposition="top center",
        textfont=dict(color=INK, size=12),
        line=dict(color=SLATE, width=3.5, shape="linear"),
        marker=dict(color=BLUE, size=10, line=dict(width=2, color="#FFFFFF")),
        fill="tozeroy", fillcolor="rgba(31,97,141,0.10)",
        customdata=[fmt(v) for v in y],
        hovertemplate="<b>%{x}</b><br>Importe: %{customdata}<extra></extra>"))
    if len(y) >= 3 and "inter" in tend:
        ajuste = np.polyval([tend["pendiente"], tend["inter"]], np.arange(len(y)))
        fig.add_trace(go.Scatter(
            x=x, y=ajuste, name="Tendencia lineal", mode="lines",
            line=dict(color=MUTED, width=2, dash="dash"), hoverinfo="skip"))
    _estilo(fig, 370, leyenda=len(y) >= 3)
    _eje_x_periodos(fig, len(y))
    fig.update_yaxes(visible=False, showgrid=False, rangemode="tozero")
    fig.update_yaxes(range=[0, max(y.max() * 1.18, 1)])
    return fig


def fig_evolucion_comparada(df: pd.DataFrame, columna: str) -> go.Figure:
    paleta = [BLUE, SLATE, "#7FB3D5", "#85929E"]
    g = df.groupby(["Periodo", columna])["Importe"].sum().reset_index()
    periodos = sorted(g["Periodo"].unique())
    etiquetas = [etiqueta_periodo(p) for p in periodos]
    fig = go.Figure()
    for i, (nombre, sub) in enumerate(g.groupby(columna)):
        s = sub.set_index("Periodo")["Importe"].reindex(periodos)
        fig.add_trace(go.Scatter(
            x=etiquetas, y=s.to_numpy(), name=str(nombre), mode="lines+markers",
            connectgaps=False, line=dict(color=paleta[i % len(paleta)], width=3.5),
            marker=dict(size=9, line=dict(width=1.5, color="#FFFFFF")),
            customdata=[fmt(v) if pd.notna(v) else "—" for v in s.to_numpy()],
            hovertemplate="<b>%{x}</b><br>" + esc(nombre) + ": %{customdata}<extra></extra>"))
    _estilo(fig, 370, leyenda=True)
    _eje_x_periodos(fig, len(periodos))
    _eje_monetario(fig, float(g["Importe"].max()) * 1.1)
    return fig


def fig_barras(serie: pd.Series, seleccion: tuple = (), alto: int = 380) -> go.Figure:
    """Barras horizontales; con selección activa se atenúan las demás."""
    s = serie.sort_values(ascending=True)
    activa = bool(seleccion)
    colores = [BLUE if (not activa or k in seleccion) else BLUE_SOFT for k in s.index]
    bordes = [NAVY if (activa and k in seleccion) else "rgba(0,0,0,0)" for k in s.index]
    textos = [fmt(v) for v in s.to_numpy()]
    fig = go.Figure(go.Bar(
        x=s.to_numpy(), y=list(s.index), orientation="h",
        marker=dict(color=colores, line=dict(color=bordes, width=2)),
        text=textos, textposition="outside", cliponaxis=False,
        textfont=dict(color=INK, size=12), customdata=textos,
        hovertemplate="<b>%{y}</b><br>Importe: %{customdata}<extra></extra>",
        selected=dict(marker=dict(opacity=1)),
        unselected=dict(marker=dict(opacity=1))))
    _estilo(fig, alto)
    fig.update_xaxes(visible=False, range=[0, float(s.max()) * 1.30 if len(s) else 1])
    fig.update_yaxes(title=None, showgrid=False, automargin=True,
                     tickfont=dict(color=INK, size=12))
    fig.update_layout(clickmode="event+select", bargap=0.35)
    return fig


def fig_naturaleza(df: pd.DataFrame) -> go.Figure:
    """Gasto bruto vs. menor gasto / ingreso por mes."""
    p = df.pivot_table(index="Periodo", columns="Naturaleza", values="Importe",
                       aggfunc="sum", fill_value=0).sort_index()
    for col in (NAT_GASTO, NAT_MENOR):
        if col not in p:
            p[col] = 0.0
    x = [etiqueta_periodo(i) for i in p.index]
    fig = go.Figure()
    for col, color in ((NAT_GASTO, BLUE), (NAT_MENOR, "#85929E")):
        fig.add_trace(go.Bar(
            x=x, y=p[col].to_numpy(), name=col, marker_color=color,
            customdata=[fmt(v) for v in p[col]],
            hovertemplate="<b>%{x}</b><br>" + col + ": %{customdata}<extra></extra>"))
    _estilo(fig, 340, leyenda=True)
    fig.update_layout(barmode="group", bargap=0.25)
    fig.update_xaxes(type="category", tickangle=-45 if len(x) > 10 else 0,
                     tickfont=dict(color=INK, size=11), linecolor=BORDE)
    _eje_monetario(fig, float(p.to_numpy().max()) * 1.1 or 1)
    return fig


def fig_estacional(df: pd.DataFrame) -> go.Figure:
    """Comparativo por año: un trazo por ejercicio sobre meses calendario."""
    g = df.groupby(["Año", "Mes"])["Importe"].sum().reset_index()
    anios = sorted(g["Año"].unique())
    paleta = {a: c for a, c in zip(anios[::-1], [BLUE, SLATE, "#7FB3D5", "#AEB6BF"])}
    fig = go.Figure()
    for a in anios:
        s = g[g["Año"] == a].set_index("Mes")["Importe"].reindex(range(1, 13))
        fig.add_trace(go.Scatter(
            x=[MESES_ABR[m].capitalize() for m in range(1, 13)], y=s.to_numpy(),
            name=str(a), mode="lines+markers", connectgaps=False,
            line=dict(color=paleta.get(a, MUTED), width=3.5 if a == anios[-1] else 2.2),
            marker=dict(size=7, line=dict(width=1, color="#FFFFFF")),
            customdata=[fmt(v) if pd.notna(v) else "—" for v in s.to_numpy()],
            hovertemplate="<b>%{x} " + str(a) + "</b><br>%{customdata}<extra></extra>"))
    _estilo(fig, 340, leyenda=True)
    fig.update_xaxes(showgrid=False, tickfont=dict(color=INK, size=11), linecolor=BORDE)
    _eje_monetario(fig, float(g["Importe"].max()) * 1.1 or 1)
    return fig


def fig_meses(serie: pd.Series, destacado: int | None = None) -> go.Figure:
    """Columnas por mes calendario (1-12) con el mes pico resaltado."""
    s = serie.reindex(range(1, 13)).fillna(0)
    colores = [SLATE if m == destacado else BLUE for m in s.index]
    textos = [fmt(v) for v in s]
    fig = go.Figure(go.Bar(
        x=[MESES_ABR[m].capitalize() for m in s.index], y=s.to_numpy(),
        marker_color=colores, text=textos, textposition="outside",
        textfont=dict(color=INK, size=11), cliponaxis=False,
        customdata=textos, hovertemplate="<b>%{x}</b><br>%{customdata}<extra></extra>"))
    _estilo(fig, 300)
    fig.update_xaxes(showgrid=False, tickfont=dict(color=INK, size=11), linecolor=BORDE)
    fig.update_yaxes(visible=False, showgrid=False, range=[0, float(s.max()) * 1.2 or 1])
    return fig


def fig_proyeccion(serie: pd.Series, tend: dict, proyeccion: float,
                   etiqueta_prox: str) -> go.Figure:
    x = [etiqueta_periodo(p) for p in serie.index]
    y = serie.to_numpy(dtype=float)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, name="Histórico", mode="lines+markers",
        line=dict(color=SLATE, width=3), marker=dict(color=BLUE, size=8,
                                                     line=dict(width=1.5, color="#FFFFFF")),
        fill="tozeroy", fillcolor="rgba(31,97,141,0.08)", hoverinfo="skip"))
    n = len(y)
    fig.add_trace(go.Scatter(
        x=[x[-1], etiqueta_prox], y=[y[-1], proyeccion], name="Proyección",
        mode="lines+markers+text", text=["", fmt(proyeccion)], textposition="top center",
        textfont=dict(color=INK, size=12),
        line=dict(color=BLUE, width=3, dash="dot"),
        marker=dict(color=GOLD, size=12, line=dict(width=2, color=NAVY))))
    _estilo(fig, 320, leyenda=True)
    _eje_x_periodos(fig, n + 1)
    fig.update_yaxes(visible=False, showgrid=False, range=[0, max(y.max(), proyeccion) * 1.2])
    return fig


# =============================================================================
# 6. ESTILO CSS Y COMPONENTES VISUALES
# =============================================================================
CSS = Template("""
html, body, .stApp, [data-testid="stAppViewContainer"] {
    background: $bg !important; color: $ink; font-family: $font;
}
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1600px; }
h1, h2, h3, h4 { color: $navy !important; font-family: $font; }
.stMarkdown p, .stMarkdown li, label, [data-testid="stWidgetLabel"] p { color: $ink; }
[data-testid="stCaptionContainer"], .stCaption { color: $muted !important; }

/* ---- Sidebar ---- */
[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid $borde; }
[data-testid="stSidebar"] label p, [data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: $ink; }
.brand { display:flex; align-items:center; gap:10px; padding:4px 0 12px 0;
         border-bottom:1px solid $borde; margin-bottom:12px; }
.brand .logo { background:$navy; color:$gold; font-weight:800; border-radius:10px;
               width:38px; height:38px; display:flex; align-items:center;
               justify-content:center; font-size:18px; }
.brand .nombre { color:$navy; font-weight:700; line-height:1.15; font-size:15px; }
.brand .nombre small { display:block; color:$muted; font-weight:500; font-size:11px; }
.sesion { border-radius:8px; padding:8px 12px; font-weight:600; font-size:13px;
          margin-bottom:8px; }
.sesion.basico { background:#FFF4D6; color:#6B4E00; border:1px solid #F0D58A; }
.sesion.premium { background:#E3F1E8; color:#14532D; border:1px solid #A8D5B8; }

/* ---- Encabezados de panel (gradiente oscuro + texto dorado) ---- */
.titulo-panel { background: linear-gradient(90deg, #101820 0%, #1a2530 100%);
    color: $gold !important; text-align:left; font-weight:600; font-size:16px;
    padding:10px 18px; border-radius:8px; margin:0 0 12px 0; letter-spacing:.4px;
    box-shadow:0 3px 10px rgba(0,0,0,.15); display:flex; justify-content:space-between;
    align-items:center; gap:12px; }
.titulo-panel span { color:#C9D6E2 !important; font-size:12px; font-weight:400;
    letter-spacing:0; }
.titulo-mini { font-size:13px; padding:7px 12px; margin:14px 0 8px 0; }

/* ---- Hero ---- */
.hero { background: linear-gradient(110deg, $navy 0%, $navy2 100%); border-radius:14px;
    padding:22px 28px; display:flex; justify-content:space-between; align-items:center;
    gap:18px; flex-wrap:wrap; border-bottom:4px solid $gold; margin-bottom:16px;
    box-shadow:0 6px 18px rgba(11,31,51,.25); }
.hero h1 { color:#FFFFFF !important; font-size:26px; margin:0; font-weight:700; }
.hero p { color:$gold !important; margin:4px 0 0 0; font-size:14px; }
.badges { display:flex; gap:8px; flex-wrap:wrap; }
.badge { background:rgba(255,255,255,.12); color:#FFFFFF; border:1px solid
    rgba(255,255,255,.35); border-radius:999px; padding:5px 12px; font-size:12px;
    font-weight:600; }

/* ---- Tarjetas KPI ---- */
.kpi { background:#FFFFFF; border:1px solid $borde; border-left:6px solid $blue;
    border-radius:10px; padding:16px 18px; min-height:128px;
    box-shadow:0 4px 14px rgba(11,31,51,.05); transition:transform .2s, box-shadow .2s; }
.kpi:hover { transform:translateY(-3px); box-shadow:0 8px 22px rgba(11,31,51,.12); }
.kpi-label { color:$muted; font-size:11.5px; font-weight:700; text-transform:uppercase;
    letter-spacing:.7px; }
.kpi-value { color:$navy; font-size:27px; font-weight:800; margin:6px 0 4px 0;
    line-height:1.1; }
.kpi-sub { color:$ink; font-size:12.5px; line-height:1.45; }
.up { color:$sube; font-weight:700; } .down { color:$baja; font-weight:700; }
.flat { color:$muted; font-weight:700; }
.nota { background:#EAF1F8; border:1px solid #C9DBEA; color:$navy; border-radius:8px;
    padding:8px 14px; font-size:12.5px; margin:12px 0 4px 0; }

/* ---- Barra de segmento activo ---- */
.foco { background:#FFFFFF; border:1px solid $borde; border-left:6px solid $gold;
    border-radius:10px; padding:10px 16px; color:$ink; font-size:13.5px; }
.chip { display:inline-block; background:$bluesoft; color:$navy; border:1px solid $blue;
    border-radius:999px; padding:2px 11px; margin:2px 4px 2px 0; font-weight:600;
    font-size:12.5px; }

/* ---- Controles ---- */
span[data-baseweb="tag"] { background:$bluesoft !important; border:1px solid $blue !important; }
span[data-baseweb="tag"] span, span[data-baseweb="tag"] svg { color:$navy !important; fill:$navy !important; }
div[data-baseweb="slider"] [role="slider"] { background-color:$blue !important; }
[data-testid="stThumbValue"], [data-testid="stSliderThumbValue"] { background:$slate !important;
    color:#FFFFFF !important; font-weight:700; border-radius:4px; padding:0 6px; }
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
    background:#FFFFFF !important; color:$ink !important; border-color:$borde !important; }
div[data-baseweb="select"] input, div[data-baseweb="input"] input { color:$ink !important; }
ul[role="listbox"] { background:#FFFFFF !important; }
ul[role="listbox"] li { color:$ink !important; }
div[data-testid="stCheckbox"] label span { color:$ink; }
button[kind="primary"], button[data-testid="stBaseButton-primary"] {
    background:$navy !important; color:#FFFFFF !important; border:1px solid $navy !important;
    border-radius:8px; font-weight:600; }
button[kind="primary"]:hover, button[data-testid="stBaseButton-primary"]:hover {
    border-color:$gold !important; color:$gold !important; }
button[kind="secondary"], button[data-testid="stBaseButton-secondary"] {
    background:#FFFFFF !important; color:$navy !important; border:1px solid $blue !important;
    border-radius:8px; font-weight:600; }
button[kind="secondary"]:hover, button[data-testid="stBaseButton-secondary"]:hover {
    background:$bluesoft !important; }
button[kind="primary"] p, button[data-testid="stBaseButton-primary"] p { color:inherit !important; }
button[kind="secondary"] p, button[data-testid="stBaseButton-secondary"] p { color:$navy !important; }

/* ---- Pestañas ---- */
button[data-baseweb="tab"] { font-weight:600; font-size:15px; color:$muted; }
button[data-baseweb="tab"][aria-selected="true"] { color:$navy; }
[data-baseweb="tab-highlight"] { background-color:$blue !important; height:3px; }

/* ---- Contenedores, tablas y chat ---- */
[data-testid="stVerticalBlockBorderWrapper"] { background:#FFFFFF; border:1px solid $borde !important;
    border-radius:12px; box-shadow:0 3px 12px rgba(11,31,51,.05); }
[data-testid="stDataFrame"] { border:1px solid $borde; border-radius:10px; overflow:hidden; }
[data-testid="stChatMessage"] { background:#FFFFFF; border:1px solid $borde;
    border-radius:12px; padding:14px 16px; margin-bottom:10px; }
[data-testid="stChatMessage"]:has([data-testid*="AvatarUser"]) { background:#EAF1F8; }
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { color:$ink; }
[data-testid="stChatInput"] { border:1px solid $blue; border-radius:12px; background:#FFFFFF; }
.login-head { color:$navy; font-size:26px; font-weight:800; text-align:center; margin-top:8vh; }
.login-sub { color:$muted; text-align:center; margin-bottom:18px; font-size:14px; }
""")


def inyectar_css() -> None:
    css = CSS.substitute(
        bg=BG, ink=INK, font=FUENTE, navy=NAVY, navy2=NAVY_2, muted=MUTED, borde=BORDE,
        gold=GOLD, blue=BLUE, bluesoft=BLUE_SOFT, slate=SLATE, sube=SUBE, baja=BAJA)
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _ancho(fn) -> dict:
    """Compatibilidad: ``width='stretch'`` (nuevo) o ``use_container_width``."""
    try:
        if "width" in inspect.signature(fn).parameters:
            return {"width": "stretch"}
    except (TypeError, ValueError):
        pass
    return {"use_container_width": True}


def panel(titulo: str, sub: str = "", mini: bool = False, destino=None) -> None:
    clase = "titulo-panel titulo-mini" if mini else "titulo-panel"
    extra = f"<span>{esc(sub)}</span>" if sub else ""
    (destino or st).markdown(
        f'<div class="{clase}"><div>{esc(titulo)}</div>{extra}</div>',
        unsafe_allow_html=True)


def hero(titulo: str, subtitulo: str, badges: list) -> None:
    chips = "".join(f'<span class="badge">{esc(b)}</span>' for b in badges)
    st.markdown(
        f'<div class="hero"><div><h1>{esc(titulo)}</h1><p>{esc(subtitulo)}</p></div>'
        f'<div class="badges">{chips}</div></div>', unsafe_allow_html=True)


def kpi_card(etiqueta: str, valor: str, sub: str = "", acento: str = BLUE) -> str:
    return (f'<div class="kpi" style="border-left-color:{acento}">'
            f'<div class="kpi-label">{etiqueta}</div><div class="kpi-value">{valor}</div>'
            f'<div class="kpi-sub">{sub}</div></div>')


def delta_html(variacion: float, texto: str) -> str:
    """Gasto que sube -> rojo; gasto que baja -> verde."""
    if variacion is None or pd.isna(variacion):
        return ""
    if variacion > 0:
        return f'<span class="up">▲ {pct_txt(variacion * 100)}</span> {texto}'
    if variacion < 0:
        return f'<span class="down">▼ {pct_txt(abs(variacion) * 100)}</span> {texto}'
    return f'<span class="flat">● 0,0%</span> {texto}'


# =============================================================================
# 7. SESIÓN Y LOGIN
# =============================================================================
def init_estado() -> None:
    defaults = dict(autenticado=False, tipo_usuario=None, hora_login=0.0,
                    expirado=False, ver_grafico=0, historial=[], estado_chat={},
                    pregunta_pendiente=None, contador_chat=0)
    for clave, valor in defaults.items():
        st.session_state.setdefault(clave, valor)


def cerrar_sesion(expirado: bool = False) -> None:
    st.session_state.autenticado = False
    st.session_state.tipo_usuario = None
    st.session_state.expirado = expirado
    st.session_state.historial = []
    st.session_state.estado_chat = {}


def pantalla_login() -> None:
    _, centro, _ = st.columns([1, 1.5, 1])
    with centro:
        st.markdown('<div class="login-head">🔐 Portal de Inteligencia Financiera</div>'
                    '<div class="login-sub">Dashboard Analítico de Tesorería · acceso '
                    'restringido</div>', unsafe_allow_html=True)
        if st.session_state.expirado:
            st.warning("⏳ Su sesión de perfil Básico finalizó (límite de "
                       f"{LIMITE_BASICO_S} segundos). Ingrese nuevamente.")
        with st.form("login"):
            clave = st.text_input("Clave de acceso", type="password")
            enviar = st.form_submit_button(
                "Ingresar de forma segura", type="primary",
                **_ancho(st.form_submit_button))
        if enviar:
            for perfil, secreto in CLAVES.items():
                if hmac.compare_digest(clave.encode(), secreto.encode()):
                    st.session_state.update(
                        autenticado=True, tipo_usuario=perfil,
                        hora_login=time.time(), expirado=False)
                    st.rerun()
            st.error("Clave incorrecta. Intente nuevamente.")
        with st.expander("Perfiles de acceso"):
            st.markdown(f"- **Básico:** sesión limitada a {LIMITE_BASICO_S} segundos.\n"
                        "- **Premium:** acceso ilimitado y asistente con IA generativa "
                        "(si está configurada).")


def verificar_expiracion() -> None:
    if (st.session_state.tipo_usuario == "Básico"
            and time.time() - st.session_state.hora_login > LIMITE_BASICO_S):
        cerrar_sesion(expirado=True)
        st.rerun()


def _reloj() -> None:
    restante = LIMITE_BASICO_S - (time.time() - st.session_state.hora_login)
    if restante <= 0:
        cerrar_sesion(expirado=True)
        st.rerun()
    st.progress(max(0.0, restante / LIMITE_BASICO_S),
                text=f"⏱ Tiempo restante: {int(restante)} s")


# Se refresca solo cada segundo y expulsa al usuario Básico sin interacción.
reloj_sesion = st.fragment(run_every=1)(_reloj) if hasattr(st, "fragment") else _reloj


def sidebar_sesion() -> None:
    with st.sidebar:
        st.markdown('<div class="brand"><div class="logo">T</div><div class="nombre">'
                    'Tesorería Analytics<small>Inteligencia financiera</small></div></div>',
                    unsafe_allow_html=True)
        if st.session_state.tipo_usuario == "Básico":
            st.markdown('<div class="sesion basico">👁️ Perfil Básico · sesión limitada</div>',
                        unsafe_allow_html=True)
            reloj_sesion()
        else:
            st.markdown('<div class="sesion premium">👑 Perfil Premium · acceso ilimitado</div>',
                        unsafe_allow_html=True)
        st.button("Cerrar sesión", key="logout", on_click=cerrar_sesion,
                  **_ancho(st.button))


def pantalla_bienvenida() -> None:
    hero(APP_TITULO, "Cargue el libro contable para desplegar el tablero",
         ["Paso 1 · Cargar Excel", "Paso 2 · Filtrar", "Paso 3 · Consultar al asistente"])
    st.info("👈 Use el panel lateral para cargar el archivo Excel normalizado "
            "(`gastos_limpios.xlsx`). Columnas esperadas: **Fe-contab-**, "
            "**Importe_Graficar** / **Importe en ML**, **Nombre cuenta**, **Tipo**, "
            "**Clave referencia 3** y **Texto**.")


def sidebar_filtros(df: pd.DataFrame) -> Filtros:
    sb = st.sidebar
    panel("Periodo de análisis", mini=True, destino=sb)
    nombres = [m.capitalize() for m in MESES_LARGO.values()]
    sel = sb.multiselect("Meses", nombres, default=nombres, label_visibility="collapsed")
    meses_ids = tuple(i for i, m in enumerate(nombres, start=1) if m in sel)
    min_y, max_y = int(df["Año"].min()), int(df["Año"].max())
    if min_y != max_y:
        anios = sb.slider("Ejercicio (año)", min_y, max_y, (min_y, max_y))
    else:
        anios = (min_y, max_y)
        sb.caption(f"Ejercicio: {min_y}")
    panel("Origen de cuenta", mini=True, destino=sb)
    tipos = tuple(t for t in sorted(df["Tipo"].unique())
                  if sb.checkbox(str(t), value=True, key=f"f_tipo_{t}"))
    panel("Naturaleza contable", mini=True, destino=sb)
    nat = sb.radio("Naturaleza", list(OPCIONES_NAT), label_visibility="collapsed")
    return Filtros(anios=tuple(anios), meses=meses_ids, tipos=tipos,
                   naturaleza=OPCIONES_NAT[nat])


# =============================================================================
# 8. ASISTENTE ANALÍTICO (motor de lenguaje natural local + LLM opcional)
# =============================================================================
MESES_NOMBRES = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4, "mayo": 5, "may": 5, "junio": 6, "jun": 6,
    "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9,
    "setiembre": 9, "sept": 9, "sep": 9, "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12,
}
_MES_RE = "|".join(sorted(MESES_NOMBRES, key=len, reverse=True))
NUMEROS = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
           "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}

# Sinónimos de rubros (claves normalizadas); coincidencia por prefijo de palabra.
SIN_RUBRO = {
    "gravamen": ["gravamen", "gmf", "4x1000", "4 x mil", "cuatro por mil", "impuesto"],
    "comisiones": ["comision", "comisiones"],
    "dcto pronto pago": ["dcto", "descuento", "descuentos", "pronto pago"],
    "rendimientos": ["rendimiento", "rendimientos", "cdt"],
    "intereses": ["interes", "intereses"],
    "gastos bancarios": ["gastos bancarios", "gasto bancario"],
}
STOP_ENT = {"banco", "bancos", "de", "del", "la", "el", "los", "sas", "sa", "colombia",
            "sociedad", "por", "inversion", "mas", "para", "entre"}

INTENCIONES = {
    "ayuda": [(r"\b(ayuda|ayudame|que puedes|que sabes|que haces|como funcionas|"
               r"capacidades|que preguntas|en que me ayudas|que mas)\b", 3)],
    "saludo": [(r"\b(hola|buenas|buenos dias|buenas tardes|buenas noches|hey|saludos|"
                r"buen dia)\b", 2)],
    "gracias": [(r"\b(gracias|thanks|excelente|genial|perfecto|listo|vale)\b", 2)],
    "resumen": [(r"\b(resumen|resume|resumeme|ejecutivo|panorama|como vamos|situacion|"
                 r"hallazgos|insights?|conclusiones|diagnostico|informe|reporte|"
                 r"cuentame)\b", 3)],
    "detalle": [(r"\b(por que|porque|razon|razones|motivo|motivos|detalle|detalla|"
                 r"detalles|explica|explicame|texto|descripcion|conceptos?|causa|"
                 r"causas|que incluye|compone|desglose|desglosa|audita|auditoria)\b", 3)],
    "estacionalidad": [(r"\b(estacional\w*|temporada|fin de ano|navidad|cesantias?|"
                        r"primas?|bonificaci\w+)\b", 3),
                       (r"\b(cuando|en que mes|que mes|que meses)\b.*\b(mas|mayor|paga|"
                        r"sube|aumenta|pico)\b", 3)],
    "tendencia": [(r"\b(tendencia|proyeccion|proyecta|pronostico|prediccion|predice|"
                   r"proximo mes|mes siguiente|futuro|estimacion|estima|forecast|"
                   r"hacia donde)\b", 3)],
    "pico": [(r"\b(anomali\w+|picos?|atipic\w+|inusual\w*|raro|raros|outliers?|"
              r"disparo|disparos|salto|saltos|spike|extran\w+|sospechos\w+)\b", 3)],
    "concentracion": [(r"\b(concentracion|concentrado|dependencia|depende|riesgo|"
                       r"diversificacion|hhi)\b", 3)],
    "comparacion": [(r"\b(compara|comparar|comparame|comparacion|comparativo|versus|vs|"
                     r"contra|frente a|diferencia entre)\b", 3)],
    "variacion": [(r"\b(variacion|variaciones|crecio|crecimiento|crece|subio|sube|"
                   r"aumento|aumenta|bajo|baja|disminuyo|cambio|mom|yoy|incremento|"
                   r"reduccion|redujo|vario)\b", 2)],
    "participacion": [(r"(\bporcentaje|\bparticipacion|\brepresenta\w*|\bpeso\b|"
                       r"\bproporcion|\bque parte|%)", 3)],
    "neto": [(r"\b(neto|ingresos?|menor gasto|ahorro|saldo a favor|posicion)\b", 2)],
    "promedio": [(r"\b(promedio|media|promedia|tipico)\b", 3)],
    "conteo": [(r"\b(cuantas|cuantos|cantidad|numero de|conteo|registros|transacciones|"
                r"movimientos|operaciones|apuntes)\b", 2)],
    "ranking": [(r"\b(top|ranking|mayor|mayores|menor|menores|principal|principales|"
                 r"lidera|encabeza|mejor|mejores|peor|peores|maximo|minimo|mas alto|"
                 r"mas bajo)\b", 2), (r"\bcual(es)? (es|son|fue|fueron)\b", 1)],
    "total": [(r"\b(total|totales|suma|acumulado|cuanto|monto|importe|gastamos|gasto|"
               r"gastos|llevamos|valor)\b", 1)],
    "calidad": [(r"\b(calidad|vacios?|faltantes?|nulos?|sin descripcion|sin texto|"
                 r"incompletos?)\b", 3)],
    "filtros": [(r"\b(que filtros|filtros activos|que estoy viendo|que veo|segmento "
                 r"actual|filtro actual)\b", 3)],
    "cobertura": [(r"\b(rango de fechas|desde cuando|hasta cuando|periodo cubre|"
                   r"fechas disponibles|que anos|cobertura|que periodo)\b", 3)],
    "glosario": [(r"\b(que es|que son|que significa|significa|define|definicion|"
                  r"que quiere decir|para que sirve)\b", 3)],
    "uso": [(r"\b(como (uso|filtro|cambio|selecciono|quito|borro|descargo|exporto|"
             r"cargo|restablezco|compar\w+)|donde (veo|esta|estan)|como se (usa|hace))\b", 3)],
}
PRIORIDAD = list(INTENCIONES)
ANALITICOS = {"total", "promedio", "conteo", "ranking", "participacion", "concentracion",
              "comparacion", "variacion", "tendencia", "pico", "detalle", "estacionalidad",
              "neto", "resumen"}

DIMENSIONES = [
    ("Entidad", r"\b(banco|bancos|entidad|entidades|proveedor|proveedores|tercero|"
                r"terceros|referencia|contraparte|contrapartes|empresa|empresas)\b"),
    ("Rubro", r"\b(rubro|rubros|cuenta|cuentas|tipo de cuenta|categoria|categorias|"
              r"partida|partidas)\b"),
    ("Concepto", r"\b(concepto|conceptos|descripcion|descripciones|motivo|motivos|"
                 r"textos?)\b"),
    ("Tipo", r"\b(origen|origenes)\b"),
    ("Periodo", r"\b(mes|meses|mensual|mensuales|periodo|periodos)\b"),
    ("Anio", r"\b(ano|anos|anual|anuales|ejercicio|ejercicios)\b"),
]
ETIQUETA_DIM = {"Rubro": "rubro contable", "Entidad": "entidad / tercero",
                "Concepto": "concepto", "Tipo": "origen de cuenta", "Periodo": "mes",
                "Anio": "año"}
COL_DIM = {"Rubro": "Rubro", "Entidad": "Entidad", "Concepto": "Concepto",
           "Tipo": "Tipo", "Periodo": "Periodo", "Anio": "Año"}

# Reglas de estacionalidad de negocio: (clave de rubro, meses, insight)
REGLAS_ESTACIONALES = [
    ("gravamen", {12}, "En **diciembre** el gravamen suele subir por el pago de "
                       "**primas y bonificaciones** (más movimiento de nómina)."),
    ("gravamen", {6}, "En **junio** el gravamen se asocia a la **prima de servicios** "
                      "semestral."),
    ("gravamen", {1}, "En **enero** el gravamen refleja el pago de **cesantías**."),
    ("comision", {11, 12}, "Las comisiones de **fin de año** crecen por el **mayor "
                           "volumen de recaudo** de la temporada."),
]

GLOSARIO = [
    (r"gravamen|gmf|4x1000|cuatro por mil", "Gravamen (GMF / 4×1000)",
     "Impuesto a los movimientos financieros: 4 por mil sobre retiros y transferencias. "
     "Crece en meses de mayor movimiento de caja (nómina, primas, cesantías)."),
    (r"comision|comisiones", "Comisiones",
     "Cobros bancarios por servicios (POS, ACH, recaudo, etc.). Suelen acompañar el "
     "volumen transaccional."),
    (r"dcto|descuento|pronto pago", "Descuento por pronto pago",
     "Descuentos obtenidos de proveedores por pagar antes del vencimiento. Se registran "
     "con signo negativo: son **menor gasto**."),
    (r"rendimiento|rendimientos|cdt|fiducia", "Rendimientos",
     "Ingresos financieros de CDT, fiducias y fondos de inversión. Se contabilizan como "
     "**menor gasto / ingreso**, por eso un solo rendimiento grande puede inflar un mes."),
    (r"interes|intereses", "Intereses",
     "Costo financiero de créditos y obligaciones (pago y provisión de intereses)."),
    (r"gastos bancarios|gasto bancario", "Gastos bancarios",
     "Cargos menores de la operación bancaria; rubro de poco peso en el consolidado."),
    (r"menor gasto|ingreso", "Menor gasto / Ingreso",
     "Movimientos con signo negativo en el libro (créditos): descuentos y rendimientos. "
     "Reducen el gasto neto."),
    (r"valor absoluto|importe_graficar|importe graficar", "Valor absoluto",
     "Los gráficos suman el importe sin signo para no distorsionar barras. El **Neto "
     "contable** conserva el signo y es el resultado real (gasto − menor gasto)."),
    (r"neto", "Neto contable",
     "Gasto bruto menos menor gasto / ingreso. Si es negativo, los ingresos financieros "
     "superaron el gasto del periodo."),
    (r"mom|mes a mes|variacion mensual", "Variación MoM",
     "Cambio porcentual frente al mes calendario inmediato anterior."),
    (r"yoy|anual|ano contra ano", "Variación YoY",
     "Cambio porcentual frente al mismo mes del año anterior; elimina la estacionalidad."),
    (r"tendencia|regresion|pendiente", "Vector de tendencia",
     "Regresión lineal de grado 1 sobre el importe mensual. Se clasifica **Alcista** o "
     "**Bajista** si la pendiente supera ±1,5 % del promedio mensual; si no, **Estable**."),
    (r"hhi|concentracion", "Concentración (HHI)",
     "Índice Herfindahl-Hirschman: suma de cuadrados de las participaciones. Menos de "
     "1.500 es baja; 1.500–2.500 moderada; más de 2.500 alta."),
    (r"anomalia|atipico|pico", "Pico atípico",
     "Mes cuyo importe se aleja de la mediana más de 3 desviaciones robustas (MAD)."),
]


@dataclass
class Per:
    anio: int | None = None
    meses: frozenset | None = None
    extremos: tuple | None = None

    def etiqueta(self) -> str:
        if self.meses and len(self.meses) == 1:
            m = MESES_LARGO[next(iter(self.meses))]
        elif self.meses:
            m = f"{MESES_LARGO[min(self.meses)]}–{MESES_LARGO[max(self.meses)]}"
        else:
            m = ""
        return " ".join(x for x in (m, str(self.anio) if self.anio else "") if x)


@dataclass
class Consulta:
    texto: str
    norm: str
    tokens: list
    intent: str | None = None
    dim: str | None = None
    periodos: list = field(default_factory=list)
    rel: str | None = None
    ultimos_n: int | None = None
    historico: bool = False
    valores: dict = field(default_factory=dict)
    n: int | None = None
    asc: bool = False
    seguimiento: bool = False


@dataclass
class Ctx:
    df: pd.DataFrame
    f: Filtros
    api_key: str | None = None
    usar_llm: bool = False
    historial: list = field(default_factory=list)


@dataclass
class Alcance:
    df: pd.DataFrame
    sin_valores: pd.DataFrame
    desc: str


@dataclass
class Respuesta:
    texto: str
    tabla: pd.DataFrame | None = None
    figura: go.Figure | None = None
    pie: str = ""


# ---------------------------------------------------------------- comprensión
def _vocabulario(df: pd.DataFrame) -> list:
    v = set(MESES_NOMBRES) | set(NUMEROS)
    for pats in INTENCIONES.values():
        for rx, _ in pats:
            v |= {w for w in re.findall(r"[a-z]{4,}", rx)}
    for r in df["Rubro"].unique():
        v |= set(normalizar(r).split())
    for lista in SIN_RUBRO.values():
        for k in lista:
            v |= set(k.split())
    for e in df["Entidad"].unique():
        v |= {t for t in normalizar(e).split() if len(t) >= 4}
    for _, rx in DIMENSIONES:
        v |= {w for w in re.findall(r"[a-z]{4,}", rx)}
    v |= {"periodo", "importe", "gasto", "gastos", "mensual", "anual", "resumen",
          "ejecutivo", "tendencia", "proyeccion", "variacion", "promedio", "total",
          "detalle", "concentracion", "anomalia", "comparar", "ranking", "porcentaje"}
    return sorted(v)


def corregir_tokens(tokens: list, vocab: list) -> list:
    """Tolerancia a errores de digitación (p. ej. 'gravmen' -> 'gravamen')."""
    conocido, salida = set(vocab), []
    for t in tokens:
        if len(t) < 5 or t in conocido or t.isdigit():
            salida.append(t)
            continue
        cerca = difflib.get_close_matches(t, vocab, n=1, cutoff=0.82)
        salida.append(cerca[0] if cerca else t)
    return salida


def parsear_periodos(norm: str, anio_max: int) -> tuple:
    """Devuelve (lista de Per, resto de texto) a partir del texto normalizado."""
    pers, texto = [], norm
    rango = re.search(
        rf"\b(?:(?:entre|desde)\s+({_MES_RE})\s+(?:y|a|hasta)\s+({_MES_RE})|"
        rf"de\s+({_MES_RE})\s+(?:a|hasta)\s+({_MES_RE}))\b"
        r"(?:\s+(?:de|del)?\s*(20\d\d))?", texto)
    if rango:
        m1 = rango.group(1) or rango.group(3)
        m2 = rango.group(2) or rango.group(4)
        lo, hi = MESES_NOMBRES[m1], MESES_NOMBRES[m2]
        meses = (frozenset(range(lo, hi + 1)) if lo <= hi
                 else frozenset(list(range(lo, 13)) + list(range(1, hi + 1))))
        anio = int(rango.group(5)) if rango.group(5) else None
        pers.append(Per(anio, meses, extremos=(lo, hi)))
        texto = texto[:rango.start()] + " " + texto[rango.end():]
    for m in re.finditer(r"\b(primer|segundo|tercer|cuarto|1er|2do|3er|4to|[1-4])\s*"
                         r"(trimestre|semestre)\b(?:\s+(?:de|del)?\s*(20\d\d))?", texto):
        k = {"primer": 1, "1er": 1, "1": 1, "segundo": 2, "2do": 2, "2": 2,
             "tercer": 3, "3er": 3, "3": 3, "cuarto": 4, "4to": 4, "4": 4}[m.group(1)]
        ancho = 3 if m.group(2) == "trimestre" else 6
        if k * ancho <= 12:
            pers.append(Per(int(m.group(3)) if m.group(3) else None,
                            frozenset(range((k - 1) * ancho + 1, k * ancho + 1))))
            texto = texto.replace(m.group(0), " ")
    sueltos = []
    for m in re.finditer(rf"\b({_MES_RE})\b(?:\s+(?:de|del)\s+(20\d\d)|\s+(20\d\d))?", texto):
        anio = m.group(2) or m.group(3)
        sueltos.append(Per(int(anio) if anio else None,
                           frozenset({MESES_NOMBRES[m.group(1)]})))
    texto = re.sub(rf"\b({_MES_RE})\b(?:\s+(?:de|del)\s+(20\d\d)|\s+(20\d\d))?", " ", texto)
    anios = [int(y) for y in re.findall(r"\b(20\d\d)\b", texto)]
    if sueltos:
        distintos = {p.anio for p in sueltos if p.anio}
        if len(distintos) == 1 and anios == []:
            ya = next(iter(distintos))
            sueltos = [Per(p.anio or ya, p.meses) for p in sueltos]
        pers.extend(sueltos)
        if anios and all(p.anio is None for p in sueltos):
            pers = [Per(anios[0] if p.anio is None else p.anio, p.meses, p.extremos)
                    for p in pers]
            anios = []
    for y in anios:
        pers.append(Per(y, None))
    if re.search(r"\b(este ano|ano actual|ano en curso)\b", norm):
        pers.append(Per(anio_max, None))
    elif re.search(r"\b(ano pasado|ano anterior)\b", norm):
        pers.append(Per(anio_max - 1, None))
    return pers, texto


def detectar_valores(norm: str, df: pd.DataFrame) -> dict:
    """Encuentra rubros, entidades y orígenes mencionados en la pregunta."""
    vals: dict = {}
    for r in df["Rubro"].unique():
        rn = normalizar(r)
        claves = SIN_RUBRO.get(rn, [rn])
        hit = any(re.search(rf"\b{re.escape(k)}" + ("" if len(k) >= 5 else r"\b"), norm)
                  for k in claves)
        if hit:
            vals.setdefault("Rubro", []).append(r)
    for t in df["Tipo"].unique():
        tn = normalizar(t)
        if re.search(rf"\b(origen|tipo)\s+(de\s+cuenta\s+)?{re.escape(tn)}\b", norm) \
                or (tn == "fiducia" and "fiducia" in norm):
            vals.setdefault("Tipo", []).append(t)
    entidades = [e for e in df["Entidad"].unique() if e != "Sin entidad"]
    exactos = [e for e in entidades
               if len(normalizar(e)) >= 4 and re.search(rf"\b{re.escape(normalizar(e))}\b", norm)]
    if exactos:
        mejor = max(len(normalizar(e)) for e in exactos)
        vals["Entidad"] = [e for e in exactos if len(normalizar(e)) == mejor
                           or len(normalizar(e)) >= mejor - 2]
    else:
        toks = {t for t in norm.split() if len(t) >= 4 and t not in STOP_ENT}
        indice: dict = {}
        for e in entidades:
            for t in normalizar(e).split():
                if len(t) >= 4 and t not in STOP_ENT:
                    indice.setdefault(t, set()).add(e)
        hallados = set()
        for t in toks:
            if t in indice and len(indice[t]) <= 4:
                hallados |= indice[t]
        if hallados:
            vals["Entidad"] = sorted(hallados)
    return vals


def analizar_pregunta(texto: str, ctx: Ctx, previo: dict) -> Consulta:
    norm = normalizar(texto)
    vocab = _vocabulario(ctx.df)
    tokens = corregir_tokens(norm.split(), vocab)
    norm = " ".join(tokens)
    c = Consulta(texto=texto, norm=norm, tokens=tokens)

    anio_max = int(ctx.df["Año"].max())
    c.periodos, _ = parsear_periodos(norm, anio_max)
    c.valores = detectar_valores(norm, ctx.df)
    if re.search(r"\b(ultimo mes|mes actual|este mes|ultimo periodo)\b", norm):
        c.rel = "ultimo"
    elif re.search(r"\b(mes anterior|mes pasado|periodo anterior)\b", norm):
        c.rel = "anterior"
    m = re.search(r"\bultimos (\d+) meses\b", norm)
    if m:
        c.ultimos_n = int(m.group(1))
    c.historico = bool(re.search(
        r"\b(historic\w*|todo el periodo|todos los anos|global|desde siempre|"
        r"todo el tiempo)\b", norm))

    m = (re.search(r"\btop\s*(\d+)\b", norm)
         or re.search(r"\b(\d+)\s+(principales|mayores|menores|mejores|peores|"
                      r"entidades|bancos|rubros|conceptos|meses)\b", norm))
    if m:
        c.n = min(int(m.group(1)), 25)
    else:
        m = re.search(r"\b(?:los|las|top)\s+(un|una|dos|tres|cuatro|cinco|seis|siete|"
                      r"ocho|nueve|diez)\b", norm)
        if m:
            c.n = NUMEROS[m.group(1)]
    c.asc = bool(re.search(r"\b(menor|menores|menos|minimo|minima|mas bajo|mas baja|"
                           r"mejor|mejores|bajo|bajos)\b", norm))

    posiciones = []
    for dim, rx in DIMENSIONES:
        mm = re.search(rx, norm)
        if mm:
            posiciones.append((mm.start(), dim))
    if re.search(r"\btipo de cuenta\b", norm):
        posiciones = [(p, "Rubro" if d == "Tipo" else d) for p, d in posiciones]
    if posiciones:
        c.dim = min(posiciones)[1]

    if (c.dim == "Entidad" and re.search(r"\bbancos?\b", norm)
            and "Tipo" not in c.valores and "Entidad" not in c.valores
            and "Banco" in set(ctx.df["Tipo"])):
        c.valores["Tipo"] = ["Banco"]       # «mayor banco» -> solo origen Banco
    puntajes = {}
    for nombre, patrones in INTENCIONES.items():
        score = sum(w for rx, w in patrones if re.search(rx, norm))
        if score:
            puntajes[nombre] = score
    if ("variacion" in puntajes and "detalle" in puntajes and not c.valores
            and re.search(r"\b(por que|porque)\b", norm)):
        puntajes["variacion"] = puntajes["detalle"] + 1
    if len(tokens) > 4:
        puntajes.pop("saludo", None)
        puntajes.pop("gracias", None)
    if puntajes:
        mejor = max(puntajes.values())
        c.intent = next(n for n in PRIORIDAD if puntajes.get(n) == mejor)
        if c.intent == "comparacion" and len(c.periodos) == 1 and c.periodos[0].extremos:
            p, (lo, hi) = c.periodos[0], c.periodos[0].extremos
            c.periodos = [Per(p.anio, frozenset({lo})), Per(p.anio, frozenset({hi}))]
    elif (previo and previo.get("intent") in ANALITICOS
          and (c.periodos or c.valores or c.rel or c.ultimos_n)
          and (len(tokens) <= 3 or re.match(r"^(y|e|ahora|tambien|para|pero)\b", norm))):
        c.intent, c.seguimiento = previo.get("intent"), True
        c.dim = c.dim or previo.get("dim")
        if not c.valores:
            c.valores = previo.get("valores", {})
        if not c.periodos:
            c.periodos = previo.get("periodos", [])
    return c


# --------------------------------------------------------------------- alcance
def _mascara_per(df: pd.DataFrame, p: Per) -> pd.Series:
    m = pd.Series(True, index=df.index)
    if p.anio:
        m &= df["Año"].eq(p.anio)
    if p.meses:
        m &= df["Mes"].isin(p.meses)
    return m


def _rango_texto(df: pd.DataFrame) -> str:
    ps = sorted(df["Periodo"].unique())
    if not ps:
        return "sin datos"
    if len(ps) == 1:
        return etiqueta_periodo(ps[0])
    return f"{etiqueta_periodo(ps[0])} – {etiqueta_periodo(ps[-1])}"


def construir_alcance(ctx: Ctx, c: Consulta, con_periodos: bool = True) -> Alcance:
    explicito = bool(c.periodos) or c.historico
    base = filtrar(ctx.df, ctx.f, periodo=not explicito,
                   rubro="Rubro" not in c.valores, entidad="Entidad" not in c.valores)
    todos_anios = False
    if con_periodos and c.periodos:
        mask = pd.Series(False, index=base.index)
        for p in c.periodos:
            mask |= _mascara_per(base, p)
            todos_anios |= bool(p.meses) and p.anio is None and base["Año"].nunique() > 1
        base = base[mask]
    if con_periodos:
        if c.ultimos_n:
            base = base[base["Periodo"].isin(sorted(base["Periodo"].unique())[-c.ultimos_n:])]
        elif c.rel in ("ultimo", "anterior") and not base.empty:
            ps = sorted(base["Periodo"].unique())
            idx = -1 if c.rel == "ultimo" else -2
            if len(ps) >= abs(idx):
                base = base[base["Periodo"] == ps[idx]]
    sin_valores = base
    for dim, vs in c.valores.items():
        base = base[base[dim].isin(vs)]
    partes = [_rango_texto(base if not base.empty else sin_valores)]
    if todos_anios:
        partes.append("mes indicado en todos los años disponibles")
    if ctx.f.focos and "Rubro" not in c.valores:
        partes.append("Rubro: " + ", ".join(ctx.f.focos))
    if ctx.f.focos_ent and "Entidad" not in c.valores:
        partes.append("Entidad: " + ", ".join(ctx.f.focos_ent))
    for dim, vs in c.valores.items():
        partes.append(f"{dim}: " + ", ".join(vs[:3]) + ("…" if len(vs) > 3 else ""))
    return Alcance(base, sin_valores, " · ".join(partes))


def _pie(a: Alcance) -> str:
    return f"Base: {_num(len(a.df), 0)} registros · {a.desc}"


def _vacio(a: Alcance) -> Respuesta:
    return Respuesta("⚠️ No encontré registros para esa combinación de filtros. Pruebe "
                     "ampliar el periodo, quitar el filtro cruzado o preguntar por "
                     "**todo el histórico**.", pie=_pie(a))


# ------------------------------------------------------------------- utilidades
def _fmt_tabla(df: pd.DataFrame, dinero: tuple = (), porcentaje: tuple = (),
               signo: tuple = ()) -> pd.DataFrame:
    out = df.copy()
    for col in dinero:
        out[col] = out[col].map(cop)
    for col in porcentaje:
        out[col] = out[col].map(pct_txt)
    for col in signo:
        out[col] = out[col].map(lambda v: pct_txt(v, True))
    return out


def _agrupar(df: pd.DataFrame, dim: str) -> pd.Series:
    col = COL_DIM.get(dim, dim)
    sub = df[df["Entidad"] != "Sin entidad"] if col == "Entidad" else df
    s = sub.groupby(col)["Importe"].sum()
    if col == "Periodo":
        s.index = [etiqueta_periodo(p) for p in s.index]
    return s


def _tabla_ranking(serie: pd.Series, total: float, nombre: str) -> pd.DataFrame:
    t = pd.DataFrame({nombre: serie.index, "Importe": serie.to_numpy(),
                      "% del total": serie.to_numpy() / total * 100 if total else 0})
    return _fmt_tabla(t, dinero=("Importe",), porcentaje=("% del total",))


def _nombre_segmento(ctx: Ctx, c: Consulta) -> str:
    vs = [v for lst in c.valores.values() for v in lst]
    if vs:
        return ", ".join(vs[:3]) + ("…" if len(vs) > 3 else "")
    foco = list(ctx.f.focos) + list(ctx.f.focos_ent)
    return ", ".join(foco) if foco else "el consolidado"


def detectar_anomalias(serie: pd.Series, umbral: float = 3.0) -> list:
    if len(serie) < 6:
        return []
    med = float(serie.median())
    mad = float((serie - med).abs().median())
    if mad == 0:
        return []
    z = 0.6745 * (serie - med) / mad
    marcados = [(p, float(serie[p]), float(z[p])) for p in serie.index if abs(z[p]) >= umbral]
    return sorted(marcados, key=lambda t: -abs(t[2]))


def _motor_periodo(df: pd.DataFrame, periodo: str) -> str:
    sub = df[df["Periodo"] == periodo]
    if sub.empty or not sub["Importe"].sum():
        return ""
    tot = float(sub["Importe"].sum())
    rub = sub.groupby("Rubro")["Importe"].sum().sort_values(ascending=False)
    menor = sub.loc[sub["Naturaleza"] == NAT_MENOR, "Importe"].sum() / tot * 100
    txt = (f"rubro dominante: **{rub.index[0]}** ({pct_txt(rub.iloc[0] / tot * 100)} del mes); "
           f"{pct_txt(menor)} del importe del mes es ingreso / menor gasto")
    fila = sub.loc[sub["Importe"].idxmax()]
    if fila["Importe"] / tot >= 0.2:
        signo = "ingreso" if fila["Importe_Neto"] < 0 else "gasto"
        txt += (f"; registro destacado: **{fila['Concepto']}** ({fila['Entidad']}, "
                f"{money(fila['Importe'])}, {signo})")
    return txt


def chequeo_estacional(df: pd.DataFrame, meses: set) -> str:
    s = serie_mensual(df)
    if len(s) < 6:
        return ""
    mes = pd.Series([int(p[5:]) for p in s.index], index=s.index)
    dentro, fuera = s[mes.isin(meses)], s[~mes.isin(meses)]
    if dentro.empty or fuera.empty or fuera.mean() == 0:
        return ""
    d = (dentro.mean() / fuera.mean() - 1) * 100
    nombres = "/".join(MESES_LARGO[m] for m in sorted(meses))
    if d < -10:
        return (f"⚠️ Contraste con los datos: {nombres} promedia **{pct_txt(d, True)}** vs. "
                "el resto de meses; el efecto no es visible en este dataset.")
    return (f"📊 Contraste con los datos: {nombres} promedia **{pct_txt(d, True)}** vs. "
            "el resto de meses.")


def notas_estacionales(df: pd.DataFrame, rubros: list, meses: set) -> list:
    notas = []
    for r in rubros:
        rn = normalizar(r)
        sub = df[df["Rubro"] == r]
        for clave, ms, texto in REGLAS_ESTACIONALES:
            if clave in rn and (ms & meses):
                chk = chequeo_estacional(sub, ms)
                notas.append(f"💡 **Insight de negocio:** {texto}" + (f"\n\n{chk}" if chk else ""))
    return notas


# -------------------------------------------------------------------- respuestas
def h_saludo(ctx: Ctx, c: Consulta) -> Respuesta:
    return Respuesta("👋 ¡Hola! Soy su **asistente analítico**. Puedo calcular totales, "
                     "rankings, variaciones, tendencias, picos atípicos y explicar el "
                     "detalle contable. Escriba su consulta o toque una sugerencia.")


def h_gracias(ctx: Ctx, c: Consulta) -> Respuesta:
    return Respuesta("¡Con gusto! Si desea profundizar, puedo comparar periodos, auditar "
                     "un rubro o proyectar el próximo mes.")


def h_ayuda(ctx: Ctx, c: Consulta) -> Respuesta:
    return Respuesta(
        "🤖 **Esto es lo que puedo hacer** (respondo sobre los filtros activos del tablero; "
        "si menciona un mes o año, consulto todo el histórico):\n\n"
        "- **Cifras:** *total de gravamen*, *promedio mensual*, *¿cuántas transacciones?*\n"
        "- **Rankings:** *top 5 entidades*, *¿cuál es el mayor banco?*, *mes de mayor gasto*\n"
        "- **Participación y concentración:** *¿qué % representa comisiones?*, "
        "*¿hay concentración en pocas entidades?*\n"
        "- **Comparar:** *marzo vs abril 2025*, *gravamen vs comisiones*\n"
        "- **Variación:** *¿cuánto subió el último mes y por qué?*\n"
        "- **Tendencia:** *proyección del próximo mes*\n"
        "- **Alertas:** *¿qué meses tuvieron picos atípicos?*\n"
        "- **Auditoría:** *¿por qué gravamen en diciembre?*, *detalle de comisiones*\n"
        "- **Estacionalidad:** *¿cuándo se paga más gravamen?*\n"
        "- **Contexto:** *resumen ejecutivo*, *calidad de datos*, *¿qué es el GMF?*\n\n"
        "Puedo encadenar preguntas: después de *total de gravamen* basta con *¿y en marzo?*.")


def h_resumen(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    df = a.df
    if df.empty:
        return _vacio(a)
    total = df["Importe"].sum()
    gasto = df.loc[df["Naturaleza"] == NAT_GASTO, "Importe"].sum()
    menor = df.loc[df["Naturaleza"] == NAT_MENOR, "Importe"].sum()
    neto = df["Importe_Neto"].sum()
    s = serie_mensual(df)
    tend = analizar_tendencia(s)
    rub = df.groupby("Rubro")["Importe"].sum().sort_values(ascending=False)
    ent = _agrupar(df, "Entidad").sort_values(ascending=False)
    lineas = [
        f"**Importe acumulado:** {money(total)} en {len(s)} mes(es), media de "
        f"{money(total / len(s))} por mes.",
        f"**Composición:** gasto bruto {money(gasto)} ({pct_txt(gasto / total * 100)}) vs. "
        f"menor gasto / ingreso {money(menor)} → **neto {money(neto)}** "
        + ("(posición favorable: los ingresos financieros superan el gasto)." if neto < 0
           else "(gasto neto)."),
        f"**Rubro líder:** {rub.index[0]} con {money(rub.iloc[0])} "
        f"({pct_txt(rub.iloc[0] / total * 100)}).",
    ]
    if not ent.empty:
        top3 = ent.head(3).sum() / ent.sum() * 100
        lineas.append(f"**Entidad líder:** {ent.index[0]} ({money(ent.iloc[0])}); las 3 "
                      f"principales concentran {pct_txt(top3)}.")
    if len(s) > 1:
        lineas.append(f"**Mes pico:** {etiqueta_periodo(s.idxmax())} con {money(s.max())} "
                      f"({_num(s.max() / s.mean(), 1)}× la media).")
    if len(s) >= 3:
        lineas.append(f"**Tendencia:** {tend['estado']} ({pct_txt(tend['pct'], True)} por "
                      f"mes, R² {_num(tend['r2'], 2)}).")
    var = variacion_ultimo_mes(s)
    if var:
        lineas.append(f"**Último mes ({etiqueta_periodo(var[0])}):** "
                      f"{pct_txt(var[2] * 100, True)} vs. {etiqueta_periodo(var[1])}.")
    anom = detectar_anomalias(s)
    if anom:
        lineas.append(f"**Alertas:** {len(anom)} mes(es) atípico(s), el mayor "
                      f"{etiqueta_periodo(anom[0][0])}.")
    sd = df.loc[df["Concepto"] == SIN_DESCRIPCION, "Importe"].sum()
    if total and sd / total > 0.05:
        lineas.append(f"**Calidad:** {pct_txt(sd / total * 100)} del importe no tiene "
                      "descripción (limita la auditoría).")
    tabla = _fmt_tabla(resumen_rubros(df)[["Rubro", "Importe", "% del total", "Registros"]],
                       dinero=("Importe",), porcentaje=("% del total",))
    return Respuesta("📌 **Resumen ejecutivo — " + _nombre_segmento(ctx, c) + "**\n\n"
                     + "\n".join(f"- {x}" for x in lineas), tabla=tabla, pie=_pie(a))


def _notas(ctx: Ctx, c: Consulta, a: Alcance) -> list:
    """Insights de estacionalidad según rubro(s) y meses mencionados."""
    rubros = c.valores.get("Rubro") or list(ctx.f.focos)
    meses = set().union(*[p.meses for p in c.periodos if p.meses]) if any(
        p.meses for p in c.periodos) else set()
    return notas_estacionales(a.df, rubros, meses) if rubros and meses else []


def h_total(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    if a.df.empty:
        return _vacio(a)
    df = a.df
    total = df["Importe"].sum()
    gasto = df.loc[df["Naturaleza"] == NAT_GASTO, "Importe"].sum()
    menor = df.loc[df["Naturaleza"] == NAT_MENOR, "Importe"].sum()
    txt = (f"💰 El importe acumulado de **{_nombre_segmento(ctx, c)}** es **{money(total)}** "
           f"({_num(len(df), 0)} registros).\n\n- Gasto bruto: {money(gasto)}\n"
           f"- Menor gasto / ingreso: {money(menor)}\n- Neto contable: "
           f"**{money(df['Importe_Neto'].sum())}**")
    if not a.sin_valores.empty and len(a.sin_valores) != len(df):
        txt += (f"\n\nRepresenta el **{pct_txt(total / a.sin_valores['Importe'].sum() * 100)}** "
                "del total del periodo.")
    notas = _notas(ctx, c, a)
    if notas:
        txt += "\n\n" + "\n\n".join(notas)
    return Respuesta(txt, pie=_pie(a))


def h_promedio(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    if a.df.empty:
        return _vacio(a)
    df = a.df
    meses = df["Periodo"].nunique()
    total = df["Importe"].sum()
    mensual, ticket = total / meses, df["Importe"].mean()
    diario = total / max(df["Fecha"].nunique(), 1)
    if re.search(r"\b(transaccion\w*|ticket|registro|operacion\w*)\b", c.norm):
        foco = f"El **valor promedio por registro** es **{money(ticket)}**."
    elif re.search(r"\b(diario|dia|dias)\b", c.norm):
        foco = f"El **promedio por día con movimiento** es **{money(diario)}**."
    else:
        foco = f"El **promedio mensual** es **{money(mensual)}** ({meses} meses)."
    return Respuesta(f"⚖️ {foco}\n\n- Promedio mensual: {money(mensual)}\n- Por registro: "
                     f"{money(ticket)} (mediana {money(df['Importe'].median())})\n"
                     f"- Por día con movimiento: {money(diario)}\n\nSegmento: "
                     f"**{_nombre_segmento(ctx, c)}**.", pie=_pie(a))


def h_conteo(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    if a.df.empty:
        return _vacio(a)
    g = a.df.groupby("Rubro").size().sort_values(ascending=False)
    t = pd.DataFrame({"Rubro": g.index, "Registros": [_num(v, 0) for v in g]})
    return Respuesta(f"🔢 Hay **{_num(len(a.df), 0)} registros** en "
                     f"**{_nombre_segmento(ctx, c)}**; el rubro con más movimientos es "
                     f"**{g.index[0]}** ({_num(g.iloc[0], 0)}).", tabla=t, pie=_pie(a))


def h_ranking(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    if a.df.empty:
        return _vacio(a)
    dim = c.dim or "Rubro"
    if dim in c.valores and len(c.valores) == 1:
        dim = "Concepto" if dim == "Rubro" else "Rubro"   # evita ranking trivial
    serie = _agrupar(a.df, dim)
    if serie.empty:
        return _vacio(a)
    total = serie.sum()
    n = min(c.n or 5, len(serie))
    top = serie.nsmallest(n) if c.asc else serie.nlargest(n)
    cual = "menor" if c.asc else "mayor"
    txt = (f"🏆 Por **{ETIQUETA_DIM[dim]}**, el {cual} importe corresponde a "
           f"**{top.index[0]}** con **{money(top.iloc[0])}** "
           f"({pct_txt(top.iloc[0] / total * 100)} del total).")
    if n > 1:
        txt += f"\n\nTop {n} ({cual} a menor)." if not c.asc else f"\n\nLos {n} menores."
    return Respuesta(txt, tabla=_tabla_ranking(top, total, ETIQUETA_DIM[dim].capitalize()),
                     figura=fig_barras(top, alto=60 + 48 * n),
                     pie=_pie(a))


def h_participacion(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    if a.df.empty:
        return _vacio(a)
    tot_ref = a.sin_valores["Importe"].sum()
    if c.valores and tot_ref:
        parte = a.df["Importe"].sum()
        return Respuesta(f"📐 **{_nombre_segmento(ctx, c)}** representa el "
                         f"**{pct_txt(parte / tot_ref * 100)}** del importe del periodo "
                         f"({money(parte)} de {money(tot_ref)}).", pie=_pie(a))
    serie = _agrupar(a.df, c.dim or "Rubro").sort_values(ascending=False).head(8)
    return Respuesta("📐 Participación sobre el importe acumulado:",
                     tabla=_tabla_ranking(serie, a.df["Importe"].sum(),
                                          ETIQUETA_DIM[c.dim or "Rubro"].capitalize()),
                     pie=_pie(a))


def h_concentracion(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    s = _agrupar(a.df, "Entidad").sort_values(ascending=False)
    if s.empty:
        return _vacio(a)
    sh = s / s.sum()
    hhi = float((sh ** 2).sum() * 10000)
    nivel = "alta" if hhi > 2500 else "moderada" if hhi >= 1500 else "baja"
    return Respuesta(
        f"🎯 **Concentración {nivel}** (HHI {_num(hhi, 0)}).\n\n"
        f"- La mayor entidad (**{s.index[0]}**) pesa {pct_txt(sh.iloc[0] * 100)}.\n"
        f"- Las 3 mayores suman {pct_txt(sh.head(3).sum() * 100)} y las 5 mayores "
        f"{pct_txt(sh.head(5).sum() * 100)}.\n"
        f"- Entidades activas: {len(s)}.\n\n"
        + ("Dependencia relevante: conviene revisar condiciones y alternativas con esas "
           "contrapartes." if nivel != "baja" else "El gasto está bien distribuido."),
        tabla=_tabla_ranking(s.head(5), s.sum(), "Entidad"), figura=fig_barras(s.head(5), alto=300),
        pie=_pie(a))


def h_comparacion(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c, con_periodos=False)
    if a.df.empty:
        return _vacio(a)
    if len(c.periodos) >= 2:
        pa, pb = c.periodos[0], c.periodos[1]
        da, db = a.df[_mascara_per(a.df, pa)], a.df[_mascara_per(a.df, pb)]
        ta, tb = da["Importe"].sum(), db["Importe"].sum()
        if da.empty or db.empty:
            return Respuesta("⚠️ Alguno de los dos periodos no tiene datos en el archivo "
                             f"(cobertura: {_rango_texto(ctx.df)}).", pie=_pie(a))
        delta = tb - ta
        pct = delta / ta * 100 if ta else np.nan
        ra, rb = da.groupby("Rubro")["Importe"].sum(), db.groupby("Rubro")["Importe"].sum()
        t = pd.concat([ra.rename(pa.etiqueta()), rb.rename(pb.etiqueta())], axis=1).fillna(0)
        t["Δ"] = t.iloc[:, 1] - t.iloc[:, 0]
        t["Δ %"] = np.where(t.iloc[:, 0] != 0, t["Δ"] / t.iloc[:, 0].replace(0, np.nan) * 100, np.nan)
        t = t.sort_values("Δ", key=abs, ascending=False).reset_index()
        motor = t.iloc[0]
        sentido = "subió" if delta > 0 else "bajó"
        txt = (f"⚖️ **{pa.etiqueta().capitalize()}** vs. **{pb.etiqueta()}**: "
               f"{money(ta)} → {money(tb)}. El importe **{sentido} {money(abs(delta))}** "
               f"({pct_txt(pct, True)}).\n\nPrincipal motor: **{motor['Rubro']}** "
               f"({money(motor['Δ'])}).")
        tabla = _fmt_tabla(t, dinero=(pa.etiqueta(), pb.etiqueta(), "Δ"), signo=("Δ %",))
        return Respuesta(txt, tabla=tabla, pie=_pie(a))
    for dim in ("Rubro", "Entidad", "Tipo"):
        vs = c.valores.get(dim, [])
        if len(vs) >= 2:
            b = filtrar(ctx.df, ctx.f, periodo=not (c.periodos or c.historico),
                        rubro=False, entidad=False)
            if c.periodos:
                b = b[_mascara_per(b, c.periodos[0])]
            g = b[b[dim].isin(vs)].groupby(dim).agg(
                Importe=("Importe", "sum"), Registros=("Importe", "size"),
                Meses=("Periodo", "nunique"))
            if len(g) < 2:
                break
            g = g.sort_values("Importe", ascending=False)
            g["Media mensual"] = g["Importe"] / g["Meses"]
            t = _fmt_tabla(g.reset_index(), dinero=("Importe", "Media mensual"))
            t["Registros"] = t["Registros"].map(lambda v: _num(v, 0))
            lider, resto = g.iloc[0], g.iloc[1]
            return Respuesta(
                f"⚖️ **{g.index[0]}** supera a **{g.index[1]}** por "
                f"**{money(lider['Importe'] - resto['Importe'])}** "
                f"(×{_num(lider['Importe'] / resto['Importe'], 1)}).",
                tabla=t.drop(columns=["Meses"]),
                figura=fig_barras(g["Importe"], alto=70 + 55 * len(g)), pie=_pie(a))
    return Respuesta("🤔 Para comparar indíqueme **dos periodos** (*marzo vs abril 2025*) "
                     "o **dos elementos** (*gravamen vs comisiones*, *Bancolombia vs "
                     "Davivienda*).", pie=_pie(a))


def h_variacion(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c, con_periodos=False)
    s = serie_mensual(a.df)
    if s.empty:
        return _vacio(a)
    objetivo = s.index[-1]
    if c.periodos and c.periodos[0].meses and len(c.periodos[0].meses) == 1:
        p = c.periodos[0]
        cand = [x for x in s.index if int(x[5:]) in p.meses and (not p.anio or int(x[:4]) == p.anio)]
        if not cand:
            return Respuesta("⚠️ Ese periodo no existe en los datos (cobertura: "
                             f"{_rango_texto(ctx.df)}).", pie=_pie(a))
        objetivo = cand[-1]
    previo = str(pd.Period(objetivo, freq="M") - 1)
    if previo not in s.index:
        return Respuesta(f"ℹ️ No hay datos de {etiqueta_periodo(previo)} para calcular la "
                         "variación mensual.", pie=_pie(a))
    va, vb = float(s[previo]), float(s[objetivo])
    delta, pct = vb - va, (vb / va - 1) * 100 if va else np.nan
    sentido = "subió" if delta > 0 else "bajó"
    dim_motor = ("Entidad" if "Rubro" in c.valores or ctx.f.focos
                 else "Concepto" if "Entidad" in c.valores or ctx.f.focos_ent else "Rubro")
    ga = a.df[a.df["Periodo"] == previo].groupby(dim_motor)["Importe"].sum()
    gb = a.df[a.df["Periodo"] == objetivo].groupby(dim_motor)["Importe"].sum()
    t = pd.concat([ga.rename(etiqueta_periodo(previo)), gb.rename(etiqueta_periodo(objetivo))],
                  axis=1).fillna(0)
    t["Δ"] = t.iloc[:, 1] - t.iloc[:, 0]
    t = t.sort_values("Δ", key=abs, ascending=False).head(5).reset_index()
    t.columns = [dim_motor] + list(t.columns[1:])
    motor = t.iloc[0]
    txt = (f"📈 En **{etiqueta_periodo(objetivo)}** el importe de "
           f"**{_nombre_segmento(ctx, c)}** {sentido} **{money(abs(delta))}** "
           f"({pct_txt(pct, True)}) frente a {etiqueta_periodo(previo)}: "
           f"{money(va)} → {money(vb)}.\n\nPrincipal motor: **{motor[dim_motor]}** "
           f"({money(motor['Δ'])}); {_motor_periodo(a.df, objetivo)}.")
    yoy = str(pd.Period(objetivo, freq="M") - 12)
    if yoy in s.index and s[yoy]:
        txt += f"\n\nVs. {etiqueta_periodo(yoy)} (YoY): {pct_txt((vb / s[yoy] - 1) * 100, True)}."
    notas = notas_estacionales(a.df, list(a.df["Rubro"].unique()) if len(a.df["Rubro"].unique()) <= 2
                               else [], {int(objetivo[5:])})
    if notas:
        txt += "\n\n" + "\n\n".join(notas)
    return Respuesta(txt, tabla=_fmt_tabla(t, dinero=tuple(t.columns[1:])), pie=_pie(a))


def h_tendencia(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c, con_periodos=False)
    s = serie_mensual(a.df)
    if len(s) < 3:
        return Respuesta("ℹ️ Necesito al menos 3 meses de datos para estimar una tendencia.",
                         pie=_pie(a))
    t = analizar_tendencia(s)
    prox = str(pd.Period(s.index[-1], freq="M") + 1)
    proy = max(0.0, t["pendiente"] * len(s) + t["inter"])
    conf = "alta" if t["r2"] >= 0.5 else "moderada" if t["r2"] >= 0.2 else "baja"
    txt = (f"🔮 **Tendencia {t['estado']}** para **{_nombre_segmento(ctx, c)}**: la "
           f"pendiente es {pct_txt(t['pct'], True)} del promedio mensual por mes "
           f"({money(t['pendiente'])}/mes, R² {_num(t['r2'], 2)}).\n\n"
           f"**Proyección {etiqueta_periodo(prox)}:** {money(proy)} "
           f"(confianza {conf}).")
    if conf == "baja":
        txt += ("\n\n⚠️ El ajuste lineal explica poco la serie (picos puntuales). Úsela como "
                "referencia; para decisiones revise también el comparativo anual.")
    return Respuesta(txt, figura=fig_proyeccion(s, t, proy, etiqueta_periodo(prox)),
                     pie=_pie(a))


def h_pico(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c, con_periodos=False)
    s = serie_mensual(a.df)
    anom = detectar_anomalias(s)
    if not anom:
        return Respuesta("✅ No detecto meses atípicos (criterio: más de 3 desviaciones "
                         "robustas respecto a la mediana).", pie=_pie(a))
    filas, lineas = [], []
    for p, v, z in anom[:5]:
        filas.append({"Mes": etiqueta_periodo(p), "Importe": cop(v),
                      "Z robusto": _num(z, 1)})
        lineas.append(f"- **{etiqueta_periodo(p)}** ({money(v)}): {_motor_periodo(a.df, p)}.")
    txt = (f"🚨 **{len(anom)} mes(es) atípico(s)** en {_nombre_segmento(ctx, c)}:\n\n"
           + "\n".join(lineas)
           + "\n\n*Un pico originado en un ingreso (rendimiento) no es mayor gasto; "
             "revise la naturaleza del registro.*")
    return Respuesta(txt, tabla=pd.DataFrame(filas),
                     figura=fig_evolucion(s, analizar_tendencia(s)), pie=_pie(a))


def h_detalle(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    if a.df.empty:
        return _vacio(a)
    df = a.df
    g = df.groupby("Concepto")["Importe"].agg(["sum", "count"]).sort_values("sum", ascending=False)
    total = float(g["sum"].sum())
    con_desc = g.drop(index=SIN_DESCRIPCION, errors="ignore")
    top = con_desc.head(5)
    sd = float(g["sum"].get(SIN_DESCRIPCION, 0))
    rubros = c.valores.get("Rubro") or list(ctx.f.focos)
    cabecera = (f"📑 **Auditoría — {_nombre_segmento(ctx, c)}**" if (c.valores or ctx.f.focos
                or ctx.f.focos_ent) else "📑 **Auditoría del consolidado**")
    lineas = [f"{i}. **{k}** — {money(r['sum'])} ({pct_txt(r['sum'] / total * 100)}, "
              f"{_num(r['count'], 0)} reg.)" for i, (k, r) in enumerate(top.iterrows(), 1)]
    txt = f"{cabecera}\n\nPrincipales motivos reales de gasto:\n\n" + "\n".join(lineas)
    if sd / total > 0.03:
        txt += (f"\n\n⚠️ {money(sd)} ({pct_txt(sd / total * 100)}) está registrado **sin "
                "descripción**, por lo que no se puede explicar.")
    if not (c.valores or ctx.f.focos or ctx.f.focos_ent):
        txt += "\n\n*Indíqueme un rubro o entidad (p. ej. «detalle de comisiones») para afinar.*"
    meses = set().union(*[p.meses for p in c.periodos if p.meses]) if any(
        p.meses for p in c.periodos) else set()
    s = serie_mensual(df)
    if not meses and len(s) > 1:
        meses = {int(s.idxmax()[5:])}
    notas = notas_estacionales(df, rubros, meses)
    if notas:
        txt += "\n\n" + "\n\n".join(notas)
    t = pd.DataFrame({"Concepto": top.index, "Importe": top["sum"].to_numpy(),
                      "% del total": top["sum"].to_numpy() / total * 100,
                      "Registros": top["count"].to_numpy()})
    t = _fmt_tabla(t, dinero=("Importe",), porcentaje=("% del total",))
    return Respuesta(txt, tabla=t, pie=_pie(a))


def h_estacionalidad(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c, con_periodos=False)
    if a.df.empty:
        return _vacio(a)
    rubros = c.valores.get("Rubro") or list(ctx.f.focos) or list(a.df["Rubro"].unique())
    filas, notas, fig = [], [], None
    meses_cons = set().union(*[p.meses for p in c.periodos if p.meses]) if any(
        p.meses for p in c.periodos) else set()
    for r in rubros[:6]:
        sub = a.df[a.df["Rubro"] == r]
        mens = sub.groupby(["Año", "Mes"])["Importe"].sum().groupby("Mes").mean()
        if mens.empty:
            continue
        pico = int(mens.idxmax())
        filas.append({"Rubro": r, "Mes pico": MESES_LARGO[pico].capitalize(),
                      "Promedio en el pico": cop(mens.max()),
                      "vs. promedio anual": pct_txt((mens.max() / mens.mean() - 1) * 100, True)})
        if fig is None:
            fig = fig_meses(mens, destacado=pico)
        notas += notas_estacionales(sub, [r], meses_cons | {pico, 12, 1, 6} if not meses_cons
                                    else meses_cons)
    txt = ("🗓️ **Estacionalidad** (promedio del importe por mes calendario, entre años):"
           "\n\nLa tabla muestra el mes pico de cada rubro.")
    if notas:
        txt += "\n\n" + "\n\n".join(dict.fromkeys(notas))
    return Respuesta(txt, tabla=pd.DataFrame(filas), figura=fig if len(rubros) == 1 else None,
                     pie=_pie(a))


def h_neto(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    if a.df.empty:
        return _vacio(a)
    df = a.df
    gasto = df.loc[df["Naturaleza"] == NAT_GASTO, "Importe"].sum()
    menor = df.loc[df["Naturaleza"] == NAT_MENOR, "Importe"].sum()
    neto = df["Importe_Neto"].sum()
    top_menor = (df[df["Naturaleza"] == NAT_MENOR].groupby("Rubro")["Importe"].sum()
                 .sort_values(ascending=False))
    txt = (f"🧾 **Neto contable de {_nombre_segmento(ctx, c)}: {money(neto)}**\n\n"
           f"- Gasto bruto: {money(gasto)}\n- Menor gasto / ingreso: {money(menor)}\n\n"
           + ("Los ingresos financieros y descuentos **superan** el gasto: la posición neta es "
              "favorable." if neto < 0 else "El gasto bruto supera a los ingresos y descuentos."))
    if not top_menor.empty:
        txt += (f"\n\nPrincipal fuente de menor gasto / ingreso: **{top_menor.index[0]}** "
                f"({money(top_menor.iloc[0])}).")
    return Respuesta(txt, pie=_pie(a))


def h_calidad(ctx: Ctx, c: Consulta) -> Respuesta:
    a = construir_alcance(ctx, c)
    df = a.df
    if df.empty:
        return _vacio(a)
    sd = df["Concepto"] == SIN_DESCRIPCION
    por_rubro = (df.assign(sd=sd).groupby("Rubro")
                 .agg(Registros=("sd", "size"), Sin_desc=("sd", "sum")))
    por_rubro["% sin descripción"] = por_rubro["Sin_desc"] / por_rubro["Registros"] * 100
    por_rubro = por_rubro.sort_values("% sin descripción", ascending=False).reset_index()
    sin_ent = (df["Entidad"] == "Sin entidad").mean() * 100
    txt = (f"🧪 **Calidad de datos**\n\n- Registros sin descripción: "
           f"**{_num(sd.sum(), 0)}** ({pct_txt(sd.mean() * 100)}), equivalentes a "
           f"{money(df.loc[sd, 'Importe'].sum())}.\n- Registros sin entidad: {pct_txt(sin_ent)}.\n"
           f"- Cobertura: {_rango_texto(df)}.\n- Rubro más incompleto: "
           f"**{por_rubro.iloc[0]['Rubro']}** ({pct_txt(por_rubro.iloc[0]['% sin descripción'])}).")
    t = _fmt_tabla(por_rubro[["Rubro", "Registros", "% sin descripción"]],
                   porcentaje=("% sin descripción",))
    return Respuesta(txt, tabla=t, pie=_pie(a))


def h_filtros(ctx: Ctx, c: Consulta) -> Respuesta:
    f = ctx.f
    nat = f.naturaleza or "Todo (valor absoluto)"
    partes = [f"- **Años:** {f.anios[0]}–{f.anios[1]}",
              "- **Meses:** " + ", ".join(MESES_LARGO[m] for m in f.meses),
              "- **Origen de cuenta:** " + ", ".join(f.tipos), f"- **Naturaleza:** {nat}"]
    if f.focos:
        partes.append("- **Rubro seleccionado (filtro cruzado):** " + ", ".join(f.focos))
    if f.focos_ent:
        partes.append("- **Entidad seleccionada (filtro cruzado):** " + ", ".join(f.focos_ent))
    return Respuesta("🎛️ **Filtros activos del tablero**\n\n" + "\n".join(partes))


def h_cobertura(ctx: Ctx, c: Consulta) -> Respuesta:
    df = ctx.df
    return Respuesta(f"🗂️ El archivo cubre **{_rango_texto(df)}**: "
                     f"{_num(len(df), 0)} registros, {df['Rubro'].nunique()} rubros y "
                     f"{df['Entidad'].nunique()} entidades.")


def h_glosario(ctx: Ctx, c: Consulta) -> Respuesta:
    hallados = [(t, d) for rx, t, d in GLOSARIO if re.search(rf"\b({rx})\b", c.norm)]
    if hallados:
        return Respuesta("\n\n".join(f"📖 **{t}**\n\n{d}" for t, d in hallados[:3]))
    return Respuesta("📖 Puedo explicar: " + ", ".join(t for _, t, _ in GLOSARIO)
                     + ". Pregunte, por ejemplo, *¿qué es el gravamen?*")


def h_uso(ctx: Ctx, c: Consulta) -> Respuesta:
    guia = [
        (r"cruzad\w*|seleccion\w*|clic|click",
         "**Filtro cruzado:** haga clic en una barra de *Rubro* o de *Entidad*; todo el "
         "tablero se recalcula. Use *Quitar filtro* para limpiar."),
        (r"restablec\w*|quito|borro|limpi\w*",
         "**Quitar filtros:** botón *Quitar filtro cruzado* en la franja de segmento activo."),
        (r"compar\w*", "**Comparar:** en *Modo de análisis* elija *Comparativa de cuentas* o "
                       "*de entidades* (hasta 2)."),
        (r"descarg\w*|export\w*|csv",
         "**Exportar:** pestaña *Detalle y variación* → *Descargar matriz (CSV)*."),
        (r"carg\w*|archivo|excel", "**Cargar datos:** panel lateral → *Origen de datos*."),
        (r"sesion|tiempo|basico|premium",
         "**Sesión:** el perfil Básico dura 60 s; Premium es ilimitado."),
    ]
    sel = [t for rx, t in guia if re.search(rx, c.norm)]
    return Respuesta("🧭 " + "\n\n".join(sel or [t for _, t in guia]))


def h_perfil(ctx: Ctx, c: Consulta) -> Respuesta:
    """Menciona un segmento sin pedir nada concreto: perfil rápido."""
    a = construir_alcance(ctx, c)
    if a.df.empty:
        return _vacio(a)
    df = a.df
    s = serie_mensual(df)
    tot_ref = a.sin_valores["Importe"].sum()
    top = (df.groupby("Concepto")["Importe"].sum().drop(SIN_DESCRIPCION, errors="ignore")
           .sort_values(ascending=False).head(3))
    txt = (f"🔎 **{_nombre_segmento(ctx, c)}** acumula **{money(df['Importe'].sum())}** "
           f"({pct_txt(df['Importe'].sum() / tot_ref * 100)} del periodo) en "
           f"{_num(len(df), 0)} registros.\n\n- Mes pico: {etiqueta_periodo(s.idxmax())} "
           f"({money(s.max())}).\n- Media mensual: {money(s.mean())}.")
    if not top.empty:
        txt += "\n- Principales conceptos: " + "; ".join(
            f"{k} ({money(v)})" for k, v in top.items()) + "."
    notas = _notas(ctx, c, a)
    if notas:
        txt += "\n\n" + "\n\n".join(notas)
    return Respuesta(txt + "\n\n*¿Quiere el detalle, la tendencia o una comparación?*",
                     figura=fig_evolucion(s, analizar_tendencia(s)) if len(s) > 1 else None,
                     pie=_pie(a))


HANDLERS = {
    "saludo": h_saludo, "gracias": h_gracias, "ayuda": h_ayuda, "resumen": h_resumen,
    "total": h_total, "promedio": h_promedio, "conteo": h_conteo, "ranking": h_ranking,
    "participacion": h_participacion, "concentracion": h_concentracion,
    "comparacion": h_comparacion, "variacion": h_variacion, "tendencia": h_tendencia,
    "pico": h_pico, "detalle": h_detalle, "estacionalidad": h_estacionalidad,
    "neto": h_neto, "calidad": h_calidad, "filtros": h_filtros, "cobertura": h_cobertura,
    "glosario": h_glosario, "uso": h_uso,
}


# ------------------------------------------------------------------ LLM opcional
def obtener_api_key() -> str | None:
    clave = os.environ.get("ANTHROPIC_API_KEY")
    if clave:
        return clave
    try:
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:   # noqa: BLE001 - sin secrets.toml
        return None


def contexto_para_llm(ctx: Ctx) -> str:
    """Resumen agregado (sin registros individuales ni terceros)."""
    df = filtrar(ctx.df, ctx.f)
    if df.empty:
        return "Sin datos."
    s = serie_mensual(df)
    t = analizar_tendencia(s)
    por = lambda col, n=8: df.groupby(col)["Importe"].sum().sort_values(  # noqa: E731
        ascending=False).head(n)
    return "\n".join([
        f"Periodo: {_rango_texto(df)}; registros: {len(df)}.",
        f"Importe absoluto: {df['Importe'].sum():.0f}; neto contable: "
        f"{df['Importe_Neto'].sum():.0f} (negativo = ingresos > gastos).",
        "Por mes: " + "; ".join(f"{p}={v:.0f}" for p, v in s.items()),
        "Por rubro: " + "; ".join(f"{k}={v:.0f}" for k, v in por("Rubro").items()),
        "Por origen: " + "; ".join(f"{k}={v:.0f}" for k, v in por("Tipo").items()),
        "Top entidades: " + "; ".join(f"{k}={v:.0f}" for k, v in por("Entidad").items()),
        f"Tendencia: {t['estado']} ({t['pct']:.2f}% mensual, R2 {t['r2']:.2f}).",
        "Nota: Gravamen=GMF 4x1000; Rendimientos y Dcto pronto pago son menor gasto.",
    ])


def consultar_llm(pregunta: str, ctx: Ctx) -> str | None:
    if not (ctx.usar_llm and ctx.api_key):
        return None
    historial = "\n".join(f"{r}: {t}" for r, t in ctx.historial[-6:])
    cuerpo = {
        "model": MODELO_LLM, "max_tokens": 700,
        "system": ("Eres un analista financiero senior de tesorería. Responde en español, "
                   "claro y breve, solo con base en el contexto de datos entregado; si el "
                   "dato no está, dilo. Escapa el símbolo de pesos como \\$."),
        "messages": [{"role": "user", "content":
                      f"CONTEXTO:\n{contexto_para_llm(ctx)}\n\nCONVERSACIÓN:\n{historial}\n\n"
                      f"PREGUNTA: {pregunta}"}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=json.dumps(cuerpo).encode(),
        headers={"x-api-key": ctx.api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:   # noqa: S310
            data = json.load(r)
        txt = "".join(b.get("text", "") for b in data.get("content", [])
                      if b.get("type") == "text").strip()
        return txt or None
    except Exception:   # noqa: BLE001 - la IA generativa es opcional
        return None


def sugerencias(ctx: Ctx) -> list:
    df = filtrar(ctx.df, ctx.f)
    top_r = (df.groupby("Rubro")["Importe"].sum().idxmax() if not df.empty else "Gravamen")
    return ["Resumen ejecutivo", f"¿Por qué {top_r}? Detalle de conceptos",
            "¿Cuál es la entidad con mayor gasto?", "¿Qué meses tuvieron picos atípicos?",
            "Proyección del próximo mes", "¿Hay concentración en pocas entidades?"]


def fallback(ctx: Ctx, c: Consulta) -> Respuesta:
    df = filtrar(ctx.df, ctx.f)
    top = (df.groupby("Rubro")["Importe"].sum().idxmax() if not df.empty else "Gravamen")
    return Respuesta(
        "🤖 No logré identificar con claridad su consulta, pero puedo ayudarle con "
        "totales, rankings, comparaciones, variaciones, tendencia y auditoría de conceptos."
        f"\n\nEl rubro de mayor gasto ahora es **{top}**. Pruebe con:\n\n"
        f"1. *¿Por qué {top}? Detalle de conceptos*\n2. *¿Cuál es el mayor banco?*\n"
        "3. *Resumen ejecutivo*\n\nEscriba **ayuda** para ver todo lo que sé hacer.")


def responder(texto: str, ctx: Ctx, previo: dict) -> tuple:
    """Orquesta: comprensión -> handler -> (LLM / sugerencias) -> estado."""
    c = analizar_pregunta(texto, ctx, previo)
    if ctx.df.empty:
        return Respuesta("⚠️ No hay datos cargados."), previo
    if c.intent in HANDLERS:
        resp = HANDLERS[c.intent](ctx, c)
    elif c.valores or c.periodos or c.rel or c.ultimos_n:
        resp = h_perfil(ctx, c) if c.valores else h_resumen(ctx, c)
    else:
        llm = consultar_llm(texto, ctx)
        if llm:
            resp = Respuesta(llm, pie="Respuesta generada con IA a partir de un resumen "
                                      "agregado de los datos filtrados.")
        else:
            resp = fallback(ctx, c)
    nuevo = dict(intent=c.intent, dim=c.dim, valores=c.valores, periodos=c.periodos) \
        if c.intent in HANDLERS else previo
    return resp, nuevo


# =============================================================================
# 9. PÁGINAS DEL TABLERO
# =============================================================================
MODO_INDIVIDUAL = "Individual / Cruzado (interactivo)"
MODO_CUENTAS = "Comparativa de cuentas"
MODO_ENTIDADES = "Comparativa de entidades"


def leer_seleccion(clave: str) -> tuple:
    """Lee los puntos seleccionados de un gráfico Plotly (evento nativo)."""
    estado = st.session_state.get(clave)
    if not estado:
        return ()
    try:
        puntos = estado.get("selection", {}).get("points", [])
    except AttributeError:
        return ()
    return tuple(dict.fromkeys(p["y"] for p in puntos if "y" in p))


def _reset_foco() -> None:
    st.session_state.ver_grafico += 1


def render_foco(f: Filtros, modo: str, interactivo: bool) -> None:
    izq, der = st.columns([5, 1.3])
    partes = [f'<span class="chip">Rubro · {esc(x)}</span>' for x in f.focos]
    partes += [f'<span class="chip">Entidad · {esc(x)}</span>' for x in f.focos_ent]
    if partes:
        titulo = "Comparativa activa" if not interactivo else "Filtro cruzado activo"
        izq.markdown(f'<div class="foco"><b>🎯 {titulo}:</b> {"".join(partes)}</div>',
                     unsafe_allow_html=True)
    else:
        izq.markdown('<div class="foco"><b>🌐 Segmento analizado:</b> Consolidado global '
                     '— haga clic en una barra para filtrar todo el tablero.</div>',
                     unsafe_allow_html=True)
    if interactivo and partes:
        der.button("✖ Quitar filtro cruzado", key="reset_foco", on_click=_reset_foco,
                   **_ancho(st.button))


def render_kpis(dyn: pd.DataFrame, serie: pd.Series, tend: dict) -> None:
    total = float(dyn["Importe"].sum())
    prom = total / len(serie) if len(serie) else 0.0
    gasto = float(dyn.loc[dyn["Naturaleza"] == NAT_GASTO, "Importe"].sum())
    menor = float(dyn.loc[dyn["Naturaleza"] == NAT_MENOR, "Importe"].sum())
    neto = float(dyn["Importe_Neto"].sum())
    var = variacion_ultimo_mes(serie)
    sub1 = f"Media mensual: <b>{money_html(prom)}</b>"
    if var:
        sub1 += "<br>" + delta_html(var[2], f"{etiqueta_periodo(var[0])} vs. "
                                            f"{etiqueta_periodo(var[1])}")
    p_g = gasto / total * 100 if total else 0
    color_neto = BAJA if neto < 0 else SUBE
    lectura = "Posición favorable" if neto < 0 else "Gasto neto"
    cols = st.columns(5)
    tarjetas = [
        kpi_card("Importe acumulado", money_html(total), sub1, BLUE),
        kpi_card("Gasto bruto", money_html(gasto),
                 f"{pct_txt(p_g)} del importe<br>{_num(int((dyn['Naturaleza'] == NAT_GASTO).sum()), 0)} registros",
                 SLATE),
        kpi_card("Menor gasto / ingreso", money_html(menor),
                 f"{pct_txt(100 - p_g if total else 0)} del importe<br>Descuentos y rendimientos",
                 "#85929E"),
        kpi_card("Neto contable",
                 f'<span style="color:{color_neto}">{money_html(neto)}</span>',
                 f"Gasto − menor gasto/ingreso<br><b>{lectura}</b>", color_neto),
        kpi_card("Vector de tendencia", tend["estado"],
                 (f"{pct_txt(tend['pct'], True)} por mes · R² {_num(tend['r2'], 2)}<br>"
                  f"Umbral ±1,5 % del promedio") if len(serie) >= 3 else "Requiere ≥ 3 meses",
                 tend["color"]),
    ]
    for col, html_card in zip(cols, tarjetas):
        col.markdown(html_card, unsafe_allow_html=True)
    st.markdown('<div class="nota">ℹ️ Las barras y líneas usan <b>valores absolutos</b> '
                'para no distorsionar la escala; el <b>Neto contable</b> conserva el signo '
                'del libro mayor.</div>', unsafe_allow_html=True)


def _grafico(fig: go.Figure, clave: str, interactivo: bool = False) -> None:
    kwargs = dict(key=clave, config=PLOT_CFG, **_ancho(st.plotly_chart))
    if interactivo:
        kwargs.update(on_select="rerun", selection_mode="points")
    st.plotly_chart(fig, **kwargs)


def render_panorama(df: pd.DataFrame, f: Filtros, dyn: pd.DataFrame, serie: pd.Series,
                    tend: dict, modo: str, items: tuple, sel_r: tuple, sel_e: tuple) -> None:
    interactivo = modo == MODO_INDIVIDUAL
    ver = st.session_state.ver_grafico
    with st.container(border=True):
        panel("Evolución cronológica del importe", "Línea de tendencia lineal punteada")
        if not interactivo and items:
            columna = "Rubro" if modo == MODO_CUENTAS else "Entidad"
            _grafico(fig_evolucion_comparada(dyn, columna), "g_evol_comp")
        else:
            _grafico(fig_evolucion(serie, tend), "g_evol")

    izq, der = st.columns(2)
    data_r = dyn if not interactivo else filtrar(df, f, rubro=False)
    data_e = dyn if not interactivo else filtrar(df, f, entidad=False)
    with izq, st.container(border=True):
        panel("Distribución por rubro contable",
              "👆 clic para filtrar" if interactivo else "bloqueado en comparativa")
        _grafico(fig_barras(data_r.groupby("Rubro")["Importe"].sum(), sel_r),
                 f"g_rubro_{ver}" if interactivo else "g_rubro_fijo", interactivo)
    with der, st.container(border=True):
        panel("Concentración por entidad / tercero",
              "👆 clic para filtrar (top 15)" if interactivo else "top 15")
        ent = (data_e[data_e["Entidad"] != "Sin entidad"].groupby("Entidad")["Importe"].sum())
        top = ent.nlargest(15)
        extra = ent[ent.index.isin(sel_e) & ~ent.index.isin(top.index)]
        _grafico(fig_barras(pd.concat([top, extra]), sel_e, alto=380),
                 f"g_ent_{ver}" if interactivo else "g_ent_fijo", interactivo)

    izq2, der2 = st.columns(2)
    with izq2, st.container(border=True):
        panel("Gasto bruto vs. menor gasto / ingreso", "Por mes")
        _grafico(fig_naturaleza(dyn), "g_nat")
    with der2, st.container(border=True):
        panel("Estacionalidad: comparativo por año", "Mismo mes, distintos ejercicios")
        _grafico(fig_estacional(dyn), "g_estacional")


def _color_var(valor: float) -> str:
    if pd.isna(valor):
        return ""
    if valor > 0:
        return f"color: {SUBE}; font-weight: 700;"
    if valor < 0:
        return f"color: {BAJA}; font-weight: 700;"
    return ""


def render_detalle(dyn: pd.DataFrame) -> None:
    izq, der = st.columns([1.25, 1])
    with izq, st.container(border=True):
        panel("Matriz de variación (MoM / YoY)", "Rojo: el gasto sube · Verde: el gasto baja")
        matriz = matriz_variacion(dyn)
        if len(matriz) > 1:
            estilo = (matriz.style
                      .format({"Importe": cop, "Δ vs mes anterior": cop,
                               "Var. MoM %": lambda v: pct_txt(v, True),
                               "Var. YoY %": lambda v: pct_txt(v, True)}, na_rep="—")
                      .map(_color_var, subset=["Δ vs mes anterior", "Var. MoM %", "Var. YoY %"]))
            st.dataframe(estilo, hide_index=True, height=470, **_ancho(st.dataframe))
            st.download_button("⬇️ Descargar matriz (CSV)",
                               matriz.to_csv(index=False).encode("utf-8-sig"),
                               "matriz_variacion.csv", "text/csv", key="dl_matriz",
                               **_ancho(st.download_button))
        else:
            st.info("💡 Se requieren al menos dos periodos para calcular variaciones.")
    with der:
        with st.container(border=True):
            panel("Resumen por rubro")
            r = resumen_rubros(dyn)
            st.dataframe(
                _fmt_tabla(r, dinero=("Importe", "Gasto bruto", "Menor gasto / Ingreso", "Neto"),
                           porcentaje=("% del total",)),
                hide_index=True, **_ancho(st.dataframe))
        with st.container(border=True):
            panel("Principales conceptos (descripción contable)")
            g = (dyn[dyn["Concepto"] != SIN_DESCRIPCION].groupby("Concepto")["Importe"]
                 .agg(["sum", "count"]).sort_values("sum", ascending=False).head(10))
            t = pd.DataFrame({"Concepto": g.index, "Importe": g["sum"].to_numpy(),
                              "Registros": g["count"].to_numpy()})
            sd = dyn.loc[dyn["Concepto"] == SIN_DESCRIPCION, "Importe"].sum()
            st.dataframe(_fmt_tabla(t, dinero=("Importe",)), hide_index=True,
                         **_ancho(st.dataframe))
            if sd:
                st.caption(f"Sin descripción: {fmt(sd)} "
                           f"({pct_txt(sd / dyn['Importe'].sum() * 100)} del importe).")


def _encolar(pregunta: str) -> None:
    st.session_state.pregunta_pendiente = pregunta


def _limpiar_chat() -> None:
    st.session_state.historial = []
    st.session_state.estado_chat = {}


def _palabras(texto: str):
    for palabra in re.split(r"(\s+)", texto):
        yield palabra
        time.sleep(0.008)


def _pintar_mensaje(msg: dict, animar: bool = False) -> None:
    avatar = "🧑‍💼" if msg["rol"] == "user" else "🤖"
    with st.chat_message(msg["rol"], avatar=avatar):
        if msg["rol"] == "user":
            st.markdown(msg["texto"].replace("$", "\\$"))
            return
        resp: Respuesta = msg["resp"]
        if animar:
            st.write_stream(_palabras(resp.texto))
        else:
            st.markdown(resp.texto)
        if resp.tabla is not None and not resp.tabla.empty:
            st.dataframe(resp.tabla, hide_index=True, **_ancho(st.dataframe))
        if resp.figura is not None:
            st.plotly_chart(resp.figura, key=f"chat_fig_{msg['id']}", config=PLOT_CFG,
                            **_ancho(st.plotly_chart))
        if resp.pie:
            st.caption(resp.pie)


def render_asistente(df: pd.DataFrame, f: Filtros) -> None:
    api_key = obtener_api_key()
    premium = st.session_state.tipo_usuario == "Premium"
    with st.container(border=True):
        panel("Asistente analítico inteligente",
              "Entiende lenguaje natural · errores de digitación · preguntas encadenadas")
        c1, c2 = st.columns([3, 2])
        c1.caption("Responde sobre los filtros activos. Si menciona un mes o año, consulta "
                   "todo el histórico. Pruebe: *¿y en marzo?* después de una cifra.")
        usar_llm = False
        if api_key and premium:
            usar_llm = c2.toggle("IA generativa para preguntas abiertas", key="usar_llm",
                                 help="Envía solo un resumen agregado (sin registros ni "
                                      "terceros) al modelo de lenguaje.")
        ctx = Ctx(df=df, f=f, api_key=api_key, usar_llm=usar_llm,
                  historial=[(m["rol"], m["texto"] if m["rol"] == "user" else m["resp"].texto)
                             for m in st.session_state.historial])
        chips = sugerencias(ctx)
        for fila in (chips[:3], chips[3:]):
            for col, texto in zip(st.columns(3), fila):
                col.button(texto, key=f"chip_{texto}", on_click=_encolar, args=(texto,),
                           **_ancho(st.button))
        if not st.session_state.historial:
            st.markdown("")
            st.info("💬 Escriba **ayuda** para ver todo lo que puedo responder, o elija una "
                    "sugerencia.")
        for msg in st.session_state.historial:
            _pintar_mensaje(msg)
        entrada = st.chat_input("Escriba su consulta analítica…")
        entrada = entrada or st.session_state.pop("pregunta_pendiente", None)
        if entrada:
            st.session_state.contador_chat += 2
            nuevo_u = dict(rol="user", texto=entrada, id=st.session_state.contador_chat - 1)
            _pintar_mensaje(nuevo_u)
            with st.spinner("Analizando datos…"):
                resp, estado = responder(entrada, ctx, st.session_state.estado_chat)
            nuevo_a = dict(rol="assistant", resp=resp, id=st.session_state.contador_chat)
            _pintar_mensaje(nuevo_a, animar=True)
            st.session_state.estado_chat = estado
            st.session_state.historial += [nuevo_u, nuevo_a]
        if st.session_state.historial:
            st.button("🧹 Nueva conversación", key="limpiar_chat", on_click=_limpiar_chat)


# =============================================================================
# 10. APLICACIÓN
# =============================================================================
def main() -> None:
    st.set_page_config(page_title=APP_TITULO, page_icon="📊", layout="wide",
                       initial_sidebar_state="expanded")
    inyectar_css()
    init_estado()
    if not st.session_state.autenticado:
        pantalla_login()
        st.stop()
    verificar_expiracion()
    sidebar_sesion()

    panel("Origen de datos", mini=True, destino=st.sidebar)
    archivo = st.sidebar.file_uploader("Libro contable (Excel)", type=["xlsx", "xls"],
                                       label_visibility="collapsed")
    if archivo is None:
        pantalla_bienvenida()
        st.stop()
    contenido = archivo.getvalue()
    try:
        with st.spinner("Construyendo modelo de datos…"):
            df = cargar_datos(hashlib.md5(contenido).hexdigest(), contenido)
    except Exception as exc:   # noqa: BLE001
        st.error(f"No fue posible procesar el archivo: {exc}")
        st.stop()
    if df.empty:
        st.warning("El archivo no contiene registros válidos.")
        st.stop()

    base = sidebar_filtros(df)
    if not base.meses or not base.tipos:
        st.warning("Seleccione al menos un mes y un origen de cuenta en el panel lateral.")
        st.stop()
    disponible = filtrar(df, base)
    if disponible.empty:
        st.warning("No hay registros con los filtros actuales.")
        st.stop()

    hero(APP_TITULO, f"Gastos financieros · {_rango_texto(disponible)} · "
                     f"{_num(len(disponible), 0)} registros",
         [f"Perfil {st.session_state.tipo_usuario}",
          next(k for k, v in OPCIONES_NAT.items() if v == base.naturaleza)])

    with st.container(border=True):
        panel("Modo de análisis", "Individual con filtro cruzado o comparativa de dos elementos")
        c1, c2 = st.columns([1, 2.4])
        modo = c1.selectbox("Modo", [MODO_INDIVIDUAL, MODO_CUENTAS, MODO_ENTIDADES],
                            label_visibility="collapsed")
        items: tuple = ()
        if modo == MODO_CUENTAS:
            items = tuple(c2.multiselect("Cuentas", sorted(disponible["Rubro"].unique()),
                                         max_selections=2, label_visibility="collapsed",
                                         placeholder="Seleccione hasta 2 cuentas"))
        elif modo == MODO_ENTIDADES:
            items = tuple(c2.multiselect("Entidades", sorted(disponible["Entidad"].unique()),
                                         max_selections=2, label_visibility="collapsed",
                                         placeholder="Seleccione hasta 2 entidades"))

    interactivo = modo == MODO_INDIVIDUAL
    ver = st.session_state.ver_grafico
    sel_r = sel_e = ()
    if interactivo:
        sel_r = tuple(x for x in leer_seleccion(f"g_rubro_{ver}")
                      if x in set(disponible["Rubro"]))
        sel_e = tuple(x for x in leer_seleccion(f"g_ent_{ver}")
                      if x in set(disponible["Entidad"]))
        f = replace(base, focos=sel_r, focos_ent=sel_e)
    elif modo == MODO_CUENTAS:
        f = replace(base, focos=items)
    else:
        f = replace(base, focos_ent=items)

    render_foco(f, modo, interactivo)
    dyn = filtrar(df, f)
    if dyn.empty:
        st.warning("La combinación seleccionada no tiene registros.")
        st.button("Restablecer filtro cruzado", on_click=_reset_foco, key="reset_vacio")
        st.stop()

    serie = serie_mensual(dyn)
    tend = analizar_tendencia(serie)
    render_kpis(dyn, serie, tend)

    t1, t2, t3 = st.tabs(["📊 Panorama", "🧮 Detalle y variación", "🤖 Asistente IA"])
    with t1:
        render_panorama(df, f, dyn, serie, tend, modo, items, sel_r, sel_e)
    with t2:
        render_detalle(dyn)
    with t3:
        render_asistente(df, f)


if __name__ == "__main__":
    main()
