"""KYC OSINT: app de Streamlit (sesión 05, dashboards).

Modo sintético: abierto; usa personas ficticias de `fixtures/` y no busca en la web.
Sus resultados están precalculados en `fixtures/resultados/`: mostrarlos no consume API.
Modo en vivo: protegido con código de acceso; busca en fuentes públicas reales.
Los informes en vivo no se guardan en disco.
Simular otro monto recalcula tope y riesgo en Python, sin volver a llamar al modelo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from kyc import pipeline, risk, sanctions
from kyc.llm import MODEL, RefusalError, make_client
from kyc.report import to_docx
from kyc.schemas import ProfileInput, SourceDoc

load_dotenv()
st.set_page_config(page_title="KYC OSINT", page_icon="🔎", layout="wide")

FIXTURES = Path(__file__).parent / "fixtures"
SAVED = FIXTURES / "resultados"
MAX_LIVE_RUNS = 5

# Paleta de la interfaz (también en .streamlit/config.toml)
GOLD, SAND, GRAPHITE, STEEL = "#facb00", "#998867", "#424242", "#686b6b"
SAND_LIGHT, LINE, STEEL_LIGHT = "#f6f4ef", "#e3ddd0", "#c4c6c6"
# El semáforo de riesgo conserva colores semánticos, en tonos sobrios
LEVEL_COLORS = {"bajo": "#2e7d4f", "medio": "#d9822b", "alto": "#c0392b", "crítico": "#7b1c1c"}
CLASS_COLORS = {"considerada": GOLD, "contexto": SAND, "descartada": STEEL_LIGHT}

CSS = f"""
<style>
.block-container {{ padding-top: 2.2rem; }}
.kyc-header {{ background: {GRAPHITE}; border-bottom: 4px solid {GOLD}; border-radius: 8px;
  padding: 1.25rem 1.5rem; margin-bottom: 1.25rem; }}
.kyc-header .brand {{ color: #fff; font-size: 1.9rem; font-weight: 700; letter-spacing: .02em; line-height: 1.1; }}
.kyc-header .brand span {{ color: {GOLD}; }}
.kyc-header .tag {{ color: #d9d9d9; font-size: .95rem; margin-top: .35rem; }}
.kyc-eyebrow {{ color: {SAND}; font-size: .75rem; font-weight: 600; letter-spacing: .12em;
  text-transform: uppercase; margin: 0 0 .25rem; }}
.kyc-note {{ background: {SAND_LIGHT}; border-left: 4px solid {SAND}; border-radius: 6px;
  padding: .8rem 1rem; color: {GRAPHITE}; margin: .25rem 0 1rem; }}
.kyc-subject {{ display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; margin: .25rem 0 .75rem; }}
.kyc-subject .name {{ font-size: 1.5rem; font-weight: 700; color: {GRAPHITE}; }}
.kyc-badge {{ font-size: .75rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
  padding: .2rem .6rem; border-radius: 999px; background: {SAND_LIGHT}; color: {SAND}; border: 1px solid {LINE}; }}
/* Tarjetas de resumen: si no caben en una fila, pasan a la siguiente (nunca se cortan) */
.kyc-wrap {{ container-type: inline-size; }}
.kyc-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: .75rem;
  margin: .5rem 0 .25rem; }}
@container (min-width: 760px) {{
  .kyc-cards {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }}
  .kyc-card .value {{ font-size: clamp(1rem, 2.1cqi, 1.4rem) !important; }}
}}
.kyc-card {{ background: {SAND_LIGHT}; border: 1px solid {LINE}; border-radius: 6px; padding: .65rem .9rem; }}
.kyc-card .label {{ font-size: .8rem; color: {STEEL}; }}
.kyc-card .value {{ font-size: 1.35rem; font-weight: 700; color: {GRAPHITE}; line-height: 1.35;
  white-space: nowrap; }}
.kyc-card .sub {{ font-size: .78rem; color: {STEEL}; }}
.kyc-reco {{ border-left: 4px solid {GOLD}; padding: .4rem .9rem; margin: 1rem 0; color: {GRAPHITE}; }}
button[kind^="primary"], button[kind^="primary"] p {{ color: {GRAPHITE} !important; font-weight: 600; }}
.stTabs [data-baseweb="tab"] p {{ font-weight: 600; }}
.kyc-footer {{ color: {STEEL}; font-size: .8rem; border-top: 1px solid {LINE}; margin-top: 2rem; padding-top: .75rem; }}
</style>
"""


def note(html: str) -> None:
    st.markdown(f"<div class='kyc-note'>{html}</div>", unsafe_allow_html=True)


def styled(chart: alt.Chart) -> alt.Chart:
    """Ejes y tipografía de los gráficos con la paleta de la app."""
    return (chart.configure_axis(labelColor=GRAPHITE, titleColor=GRAPHITE, gridColor="#eeeae1",
                                 domainColor=LINE, tickColor=LINE, labelFont="Inter", titleFont="Inter")
            .configure_legend(labelColor=GRAPHITE, titleColor=GRAPHITE, labelFont="Inter", titleFont="Inter")
            .configure_view(strokeWidth=0))


def secret(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name)
    except Exception:
        return None


@st.cache_resource(show_spinner=False)
def get_client():
    return make_client(secret("ANTHROPIC_API_KEY"))


@st.cache_resource(show_spinner="Descargando listas de sanciones OFAC y ONU…")
def warm_lists():
    return sanctions.load_lists()


@st.cache_data(show_spinner=False)
def load_personas() -> dict[str, dict]:
    personas = {}
    for f in sorted(FIXTURES.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        personas[data["id"]] = data
    return personas


@st.cache_data(show_spinner=False)
def load_saved(persona_id: str) -> pipeline.KycResult | None:
    """Resultado precalculado con `scripts/eval_synthetic.py` (US$ 0 al mostrarlo)."""
    path = SAVED / f"{persona_id}.json"
    return pipeline.load(path) if path.exists() else None


@st.cache_data(show_spinner=False, max_entries=20)
def run_synthetic(persona_id: str) -> pipeline.KycResult:
    """Respaldo si falta el resultado guardado: se calcula una vez por servidor."""
    persona = load_personas()[persona_id]
    return pipeline.run(
        ProfileInput(**persona["profile"]), get_client(),
        sources=[SourceDoc(**s) for s in persona["sources"]],
        dossier=persona.get("dossier", ""),
    )


# ---------------- Encabezado ----------------
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(
    "<div class='kyc-header'><div class='brand'>KYC <span>OSINT</span></div>"
    "<div class='tag'>Borradores de KYC para wealth management en el Perú: listas de sanciones, fuentes "
    "públicas y monto tope plausible, en un minuto y con cada hallazgo citado.</div></div>",
    unsafe_allow_html=True)

with st.sidebar:
    st.markdown("<p class='kyc-eyebrow'>KYC OSINT</p>", unsafe_allow_html=True)
    st.header("Modo")
    mode = st.radio("¿Sobre quién corre el análisis?", ["Sintético (abierto)", "En vivo (con código)"],
                    label_visibility="collapsed")
    live = mode.startswith("En vivo")
    unlocked = False
    if live:
        code = st.text_input("Código de acceso", type="password")
        expected = secret("KYC_ACCESS_CODE")
        unlocked = bool(expected) and code == expected
        if code and not unlocked:
            st.error("Código incorrecto.")
        st.caption("El modo en vivo busca en fuentes públicas reales. Está protegido para que nadie use "
                   "esta URL para perfilar a terceros.")
    st.divider()
    st.caption(f"Modelo: `{MODEL}` · búsqueda web del servidor de Anthropic")
    st.caption(f"Listas de sanciones: {sanctions.lists_date()}")
    st.caption(f"Umbrales: identidad ≥ {risk.IDENTITY_MIN}, relevancia ≥ {risk.RELEVANCE_MIN}, "
               f"homónimo < {risk.HOMONYM_MAX}")

HAS_KEY = bool(secret("ANTHROPIC_API_KEY"))
NO_KEY_MSG = "Falta `ANTHROPIC_API_KEY` (en `.env` o en los secrets de Streamlit)."

warm_lists()
result: pipeline.KycResult | None = None

# ---------------- Entrada ----------------
if not live:
    personas = load_personas()
    pid = st.selectbox("Persona sintética", list(personas),
                       format_func=lambda k: f"{personas[k]['label']}")
    persona = personas[pid]
    note(f"<b>SINTÉTICO.</b> {persona['description']} Nombres, fuentes y hechos son ficticios.")
    with st.expander("Datos de entrada y fuentes ficticias"):
        st.json(persona["profile"])
        st.dataframe(pd.DataFrame(persona["sources"])[["id", "title", "url", "date"]], hide_index=True)
    if st.button("Generar KYC", type="primary"):
        saved = load_saved(pid)
        if saved is not None:
            result = saved
            st.success(f"Resultado guardado en el repo: se generó el {saved.generated_at} en {saved.seconds:.0f} s "
                       f"por US$ {saved.usage.cost_usd():.2f}. Mostrarlo de nuevo no consume API.")
        elif not HAS_KEY:
            st.error(NO_KEY_MSG)
        else:
            with st.status("Analizando…", expanded=True) as status:
                try:
                    result = run_synthetic(pid)
                    status.update(label=f"Listo en {result.seconds:.0f} s", state="complete")
                except RefusalError as e:
                    status.update(label=str(e), state="error")
elif not unlocked:
    st.warning("Ingresa el código de acceso en la barra lateral para usar el modo en vivo.")
    st.stop()
elif not HAS_KEY:
    st.error(NO_KEY_MSG)
    st.stop()
else:
    with st.form("perfil"):
        c1, c2, c3 = st.columns(3)
        full_name = c1.text_input("Nombre completo *")
        dni = c2.text_input("DNI")
        age = c3.number_input("Edad", min_value=0, max_value=100, value=0)
        city = c1.text_input("Ciudad", value="Lima")
        occupation = c2.text_input("Ocupación declarada")
        employer = c3.text_input("Empleador o empresa declarada")
        amount = c1.number_input("Monto a invertir", min_value=0.0, value=100_000.0, step=10_000.0)
        currency = c2.selectbox("Moneda", ["USD", "PEN"])
        source_funds = c3.text_input("Fuente de fondos declarada")
        via_company = c1.checkbox("Invierte vía empresa")
        company = c2.text_input("Nombre de la empresa (si aplica)")
        abroad = c3.checkbox("Fondos provienen del exterior")
        consent = st.checkbox("Confirmo que hay base legal para este análisis (debida diligencia de un lead) "
                              "o consentimiento de la persona. Solo personas residentes en Perú.")
        submitted = st.form_submit_button("Generar KYC", type="primary")
    if submitted:
        runs = st.session_state.get("live_runs", 0)
        if not full_name.strip() or not consent:
            st.error("Falta el nombre o la confirmación de base legal.")
        elif runs >= MAX_LIVE_RUNS:
            st.error(f"Límite de {MAX_LIVE_RUNS} análisis en vivo por sesión.")
        else:
            st.session_state["live_runs"] = runs + 1
            profile = ProfileInput(
                full_name=full_name.strip(), dni=dni or None, age=int(age) or None, city=city or None,
                declared_occupation=occupation or None, employer=employer or None, amount=amount,
                currency=currency, declared_source_of_funds=source_funds or None,
                via_company=via_company, company_name=company or None, funds_from_abroad=abroad)
            with st.status("Analizando…", expanded=True) as status:
                try:
                    result = pipeline.run(profile, get_client(), progress=status.write)
                    status.update(label=f"Listo en {result.seconds:.0f} s", state="complete")
                except RefusalError as e:
                    status.update(label=str(e), state="error")

if result is not None:
    st.session_state["result"] = result
    st.session_state["result_ver"] = st.session_state.get("result_ver", 0) + 1
base = st.session_state.get("result")
if base is None:
    st.stop()

# ---------------- Resultados ----------------
st.divider()
st.markdown("<p class='kyc-eyebrow'>Borrador KYC</p>"
            f"<div class='kyc-subject'><span class='name'>{base.profile.full_name}</span>"
            f"<span class='kyc-badge'>modo {base.mode}</span></div>", unsafe_allow_html=True)

# Simular otro monto: tope, coherencia, riesgo y DD se recalculan en Python (US$ 0).
ver = st.session_state.get("result_ver", 0)
s1, s2, s3 = st.columns([2, 1, 3])
sim_amount = s1.number_input("Monto declarado (simular)", min_value=0.0, value=float(base.profile.amount),
                             step=50_000.0, format="%.0f", key=f"sim_amount_{ver}")
sim_currency = s2.selectbox("Moneda", ["USD", "PEN"], index=["USD", "PEN"].index(base.profile.currency),
                            key=f"sim_currency_{ver}")
s3.caption("Cambia el monto para ver cómo se mueven el tope, la coherencia y el riesgo. Se recalcula con las "
           "reglas en Python, sin volver a llamar al modelo: no cuesta API.")
result = pipeline.with_amount(base, sim_amount, sim_currency)
if result.amount_note:
    st.warning(result.amount_note)

r, w = result.risk, result.wealth
level_color = LEVEL_COLORS.get(r.level, GRAPHITE)


def card(label: str, value: str, sub: str = "", color: str | None = None, title: str = "") -> str:
    accent = f" style='border-left:4px solid {color}'" if color else ""
    value_color = f" style='color:{color}'" if color else ""
    return (f"<div class='kyc-card'{accent} title='{title}'><div class='label'>{label}</div>"
            f"<div class='value'{value_color}>{value}</div><div class='sub'>{sub or '&nbsp;'}</div></div>")


st.markdown("<div class='kyc-wrap'><div class='kyc-cards'>" + "".join([
    card("Riesgo", r.level.upper(), f"puntaje {r.score}", color=level_color),
    card("Debida diligencia", r.dd_type),
    card("Monto tope plausible", f"S/ {w.tope_pen:,.0f}", "ahorro acumulado, no sueldo",
         title="Ingreso laboral bruto anual (ENAHO 2024) × 35 % de ahorro, año por año de carrera, "
               "capitalizado al 4 % real"),
    card("Declarado / tope", f"{w.ratio:.2f}" if w.ratio is not None else "s/d", w.coherence.replace("_", " ")),
    card("Costo del informe", f"US$ {result.usage.cost_usd():.2f}", f"{result.seconds:.0f} s"),
]) + "</div></div>", unsafe_allow_html=True)
st.markdown(f"<div class='kyc-reco'><b>Recomendación:</b> {r.recommendation}</div>", unsafe_allow_html=True)

st.download_button("Descargar borrador KYC (.docx)", data=to_docx(result), icon=":material/download:",
                   file_name=f"KYC_{result.profile.full_name.replace(' ', '_')}.docx",
                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

t1, t2, t3, t4, t5 = st.tabs(["Factores de riesgo", "Espectro de evidencia", "Monto tope",
                              "Borrador KYC", "Fuentes"])

with t1:
    if r.factors:
        st.dataframe(pd.DataFrame([{"Regla": f.rule, "Puntos": f.points, "Detalle": f.detail,
                                    "Obliga DD reforzada": "sí" if f.forces_edd else ""} for f in r.factors]),
                     hide_index=True, width="stretch")
    else:
        st.success("No se activó ninguna regla de riesgo.")
    st.caption(f"Puntaje total {r.score}. Crítico ≥ 100, alto ≥ 40, medio ≥ 15.")
    if result.hits:
        st.markdown("**Coincidencias en listas de sanciones**")
        st.dataframe(pd.DataFrame([{"Lista": h.source, "Nombre en lista": h.listed_name,
                                    "Coincidió con": h.matched_on, "Tipo": h.kind, "Programa": h.program,
                                    "Similitud": h.score, "Fuerza": h.strength} for h in result.hits]),
                     hide_index=True, width="stretch")
    else:
        st.caption(f"Sin coincidencias en OFAC SDN ni ONU (listas del {result.lists_date}).")

with t2:
    ev = result.findings.evidence
    if ev:
        df = pd.DataFrame([{
            "id": e.source_id, "identidad": e.identity_score, "relevancia": e.relevance_score,
            "clasificación": risk.classify(e), "categoría": e.category, "dirección": e.risk_direction,
            "resumen": e.summary, "por qué identidad": e.identity_reason, "por qué relevancia": e.relevance_reason,
        } for e in ev])
        points = alt.Chart(df).mark_circle(size=240, opacity=0.95, stroke=GRAPHITE, strokeWidth=1).encode(
            x=alt.X("identidad:Q", scale=alt.Scale(domain=[0, 1]), title="¿Es la misma persona?"),
            y=alt.Y("relevancia:Q", scale=alt.Scale(domain=[0, 1]), title="¿Pesa para el riesgo o el SoW?"),
            color=alt.Color("clasificación:N", scale=alt.Scale(domain=list(CLASS_COLORS),
                                                                range=list(CLASS_COLORS.values()))),
            tooltip=["id", "categoría", "resumen", "por qué identidad", "por qué relevancia"],
        )
        labels = alt.Chart(df).mark_text(dy=-15, fontSize=11, fontWeight="bold", color=GRAPHITE).encode(
            x="identidad:Q", y="relevancia:Q", text="id:N")
        rules = alt.Chart(pd.DataFrame({"x": [risk.IDENTITY_MIN]})).mark_rule(
            strokeDash=[4, 4], color=STEEL).encode(x="x:Q") + \
            alt.Chart(pd.DataFrame({"y": [risk.RELEVANCE_MIN]})).mark_rule(
                strokeDash=[4, 4], color=STEEL).encode(y="y:Q")
        st.altair_chart(styled((points + labels + rules).properties(height=380)), width="stretch")
        st.caption("Arriba a la derecha (dorado): evidencia que alimenta el riesgo. Izquierda (gris claro): "
                   "homónimos descartados. Arena: contexto que no pesa (opiniones, menciones tangenciales).")
        st.dataframe(df.sort_values(["clasificación", "relevancia"], ascending=[True, False]),
                     hide_index=True, width="stretch")
    st.markdown(f"**Homónimos:** {result.findings.homonyms_note}")
    st.markdown(f"**PEP:** {result.findings.pep.is_pep} · {result.findings.pep.rationale}")

with t3:
    c1, c2 = st.columns([1, 1])
    comp = pd.DataFrame({
        "Componente": ["Laboral", "Empresarial", "Eventos de liquidez"],
        "Base": [w.labor_base, w.business_base, w.events_pen],
        "Tope": [w.labor_tope, w.business_tope, w.events_pen],
    })
    c1.dataframe(comp.style.format({"Base": "S/ {:,.0f}", "Tope": "S/ {:,.0f}"}), hide_index=True)
    c1.markdown(f"**Declarado:** S/ {w.declared_pen:,.0f} · **Tope:** S/ {w.tope_pen:,.0f} · "
                f"**Coherencia:** {w.coherence.replace('_', ' ')}")
    bars = pd.DataFrame({"Monto": ["Base", "Tope plausible", "Declarado"],
                         "Soles": [w.base_pen, w.tope_pen, w.declared_pen]})
    c2.altair_chart(styled(alt.Chart(bars).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("Soles:Q", title="S/"), y=alt.Y("Monto:N", sort=None, title=None),
        color=alt.Color("Monto:N", legend=None, sort=None,
                        scale=alt.Scale(domain=["Base", "Tope plausible", "Declarado"],
                                        range=[SAND, GRAPHITE, GOLD])),
        tooltip=[alt.Tooltip("Soles:Q", format=",.0f")]).properties(height=180)), width="stretch")
    st.markdown(f"**Ocupación (CNO):** {w.occupation} · {w.career_years} años de carrera · percentil tope "
                f"{w.percentile_tope}")
    st.markdown("**Supuestos:**\n" + "\n".join(f"- {a}" for a in w.assumptions))
    st.caption("La ENAHO subestima los ingresos altos: el tope es una señal para pedir sustento, no para rechazar.")

with t4:
    n = result.narrative
    st.markdown(f"#### Perfil profesional\n{n.perfil_profesional}\n\n#### Exposición política\n"
                f"{n.exposicion_politica}\n\n#### Noticias adversas\n{n.noticias_adversas}\n\n"
                f"#### Origen de la riqueza y de los fondos\n{n.origen_riqueza_y_fondos}\n\n"
                f"#### Conclusión\n{n.conclusion}")
    if n.documentos_a_solicitar:
        st.markdown("**Documentos a solicitar:**\n" + "\n".join(f"- {d}" for d in n.documentos_a_solicitar))

with t5:
    st.dataframe(pd.DataFrame([s.model_dump() for s in result.sources])[["id", "title", "url", "date"]],
                 hide_index=True, width="stretch",
                 column_config={"url": st.column_config.LinkColumn("url")})
    st.caption(f"{result.usage.input_tokens:,} tokens de entrada · {result.usage.output_tokens:,} de salida · "
               f"{result.usage.web_searches} búsquedas web · pasos: {', '.join(result.usage.calls)}")

st.markdown("<div class='kyc-footer'>Borrador para revisión del oficial de cumplimiento: no constituye una "
            "decisión de aceptación. Solo fuentes públicas; cada hallazgo lleva su fuente.</div>",
            unsafe_allow_html=True)
