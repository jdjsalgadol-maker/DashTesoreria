# 🏦 Dashboard de Tesorería — Bancos y Costos Financieros

Dashboard interactivo en Streamlit para analizar movimientos de tesorería:
comisiones, intereses, gravamen (4x1000), gastos bancarios y rendimientos
financieros, por cuenta y por banco/tercero.

## ⚠️ Corrección importante sobre las columnas

Al construir esto revisé tu archivo `gastos.xlsx` y encontré que la columna
que de verdad contiene el **nombre del banco/tercero es la columna B**
(`Clave referencia 3`), no la columna C. La columna C real (`Clave ref.1`)
es un código numérico, no un nombre. El dashboard usa la columna correcta
(los nombres de banco) — esto solo es una aclaración de la etiqueta.

## Regla de neteo (aplicada exactamente como la pediste)

Cada cuenta contable tiene una naturaleza distinta, así que conviven
positivos y negativos incluso para el mismo banco. La regla implementada:

1. **Nunca** se toma valor absoluto fila por fila (eso infla los totales).
2. Se **netea primero** (se suma con signo) por la dimensión que se esté
   analizando (cuenta, banco, cuenta+banco, cuenta+periodo, etc.).
3. **Solo al final** se aplica valor absoluto sobre ese neto, para que las
   gráficas siempre muestren magnitudes positivas sin perder la lógica
   contable.

Esto está centralizado en la función `netear()` de `app.py` — todas las
secciones del dashboard la usan, así que el criterio es consistente en
todo el tablero.

## Qué incluye

1. **KPIs maestros** — Resultado Financiero Neto (Ingresos - Gastos),
   Gastos Financieros totales, Ingresos Financieros (Rendimientos), bancos
   activos, movimientos analizados.
2. **Análisis por Cuenta** — barras con colores vivos.
3. **Desglose de Bancos por Cuenta** — sunburst interactivo.
4. **Ranking de Bancos** — top N bancos/terceros por costo financiero
   (slider ajustable).
5. **Tendencia Temporal** — evolución mensual por cuenta con línea de
   tendencia (regresión lineal simple, sin depender de `statsmodels` para
   mantener el despliegue liviano) e insight automático de qué cuenta sube
   o baja más rápido.
6. **Versus Temporal** — comparador de periodos flexible: puedes comparar
   un mes puntual, un trimestre, o el mismo mes en años distintos,
   seleccionando cualquier combinación de meses en Periodo A y B.

Filtros globales en la barra lateral: año, cuenta y banco/tercero — se
aplican a todo el dashboard.

## Cómo correr localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

Coloca tu Excel en `data/raw/`, o cárgalo desde el uploader de la barra
lateral. Probado con `streamlit.testing.v1.AppTest` — cero excepciones,
incluyendo casos límite (filtros vacíos, un solo año, un solo banco).

## Desplegar en GitHub + Streamlit Community Cloud

```bash
git init && git add . && git commit -m "Dashboard tesorería"
git branch -M main
git remote add origin https://github.com/<tu-usuario>/<tu-repo>.git
git push -u origin main
```

Luego en [share.streamlit.io](https://share.streamlit.io): New app → tu
repo → rama `main` → archivo `app.py` → Deploy.

## Actualizar los datos

Reemplaza `data/raw/gastos.xlsx` con el export más reciente (mismas
columnas: `Importe en ML`, `Nombre cuenta`, `Clave referencia 3`,
`Fe-contab-`) y vuelve a desplegar, o simplemente cárgalo desde el
uploader de la barra lateral sin tocar el repositorio.
