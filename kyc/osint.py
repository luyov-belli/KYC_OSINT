"""Investigación OSINT con fuentes públicas (sesión 03: scraping y APIs).

Claude busca en la web con la herramienta de búsqueda del servidor (web_search),
guiado por consultas plantilla pensadas para el Perú. Todas las URLs que
devuelve el buscador se guardan como fuentes numeradas: la extracción solo
puede citar esas fuentes, así que no puede inventar una URL.

Límites deliberados: sin login, sin captchas, sin redes que lo prohíban
(LinkedIn se ve solo por lo que indexa el buscador).
"""

from __future__ import annotations

import anthropic

from .llm import BETAS, FALLBACKS, MODEL, UsageTracker, _check
from .schemas import ProfileInput, SourceDoc

MAX_SEARCHES = 8
MAX_FETCHES = 3

PERU_DOMAINS = [
    "infogob.jne.gob.pe (historial político y candidaturas)",
    "elperuano.pe (normas legales y designaciones)",
    "gob.pe y portales de transparencia (funcionarios)",
    "contraloria.gob.pe (declaraciones juradas)",
    "medios: elcomercio.pe, larepublica.pe, gestion.pe, rpp.pe, infobae.com/peru, ojo-publico.com, convoca.pe, idl-reporteros.pe",
]

RESEARCH_SYSTEM = """Eres investigador OSINT de un área de cumplimiento (KYC/PLAFT) en Perú.
Investigas a un posible cliente usando SOLO fuentes públicas, para un borrador de debida diligencia.

Qué buscar (haz entre 5 y 8 búsquedas, en español, siempre con contexto Perú):
1. Empleo y cargos actuales y pasados; empresa y puesto.
2. Cargos públicos o políticos (PEP), propios o de familiares cercanos.
3. Noticias adversas: lavado de activos, corrupción, fraude, evasión, investigaciones fiscales o procesos judiciales.
4. Empresas que posee o dirige (RUC, accionista, gerente) y su tamaño.
5. Eventos de liquidez públicos: venta de empresa o inmueble, herencia, premios.

Reglas:
- Usa los desambiguadores para separar homónimos. Si aparece un homónimo con antecedentes, regístralo como homónimo.
- No inventes. Si no encuentras algo, dilo.
- Al final escribe notas breves: una línea por hallazgo, con la URL de donde sale."""


def research_queries(p: ProfileInput) -> list[str]:
    name = f'"{p.full_name}"'
    q = [
        f"{name} Perú",
        f"{name} cargo OR gerente OR director OR funcionario",
        f"{name} lavado OR fiscalía OR denuncia OR investigación OR sentencia",
        f"{name} site:infogob.jne.gob.pe OR site:elperuano.pe OR site:gob.pe",
        f"{name} empresa OR RUC OR accionista",
    ]
    if p.employer:
        q.append(f'{name} "{p.employer}"')
    if p.via_company and p.company_name:
        q.append(f'"{p.company_name}" Perú RUC')
    return q


def research(client: anthropic.Anthropic, profile: ProfileInput,
             tracker: UsageTracker) -> tuple[list[SourceDoc], str]:
    """Devuelve (fuentes numeradas, notas del investigador)."""
    prompt = (
        f"Posible cliente: {profile.full_name}\n"
        f"Residente en Perú. Desambiguadores: {profile.disambiguators()}\n\n"
        "Consultas sugeridas (ajústalas según lo que encuentres):\n- "
        + "\n- ".join(research_queries(profile))
        + "\n\nFuentes peruanas útiles:\n- " + "\n- ".join(PERU_DOMAINS)
    )
    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES,
         "user_location": {"type": "approximate", "country": "PE", "city": "Lima",
                           "timezone": "America/Lima"}},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": MAX_FETCHES},
    ]
    user_msg = {"role": "user", "content": prompt}
    content_blocks: list = []

    # La búsqueda del servidor puede pausar el turno (pause_turn): se reenvía lo
    # acumulado como un solo turno del asistente y el servidor continúa.
    for _ in range(4):
        messages = [user_msg] + ([{"role": "assistant", "content": content_blocks}] if content_blocks else [])
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=BETAS,
            fallbacks=FALLBACKS,
            output_config={"effort": "medium"},
            system=RESEARCH_SYSTEM,
            tools=tools,
            messages=messages,
        )
        tracker.add("busqueda", resp.usage)
        content_blocks = content_blocks + list(resp.content)
        if resp.stop_reason == "pause_turn":
            continue
        _check(resp)
        break

    return _collect_sources(content_blocks), _collect_notes(content_blocks)


def _collect_sources(blocks: list) -> list[SourceDoc]:
    """Numera cada URL única que devolvió el buscador o que se citó en el texto."""
    by_url: dict[str, SourceDoc] = {}

    def add(url: str, title: str, date: str | None = None, text: str = "") -> None:
        if not url:
            return
        if url in by_url:
            doc = by_url[url]
            if text and text not in doc.text:
                doc.text = (doc.text + "\n" + text).strip()[:1500]
            return
        by_url[url] = SourceDoc(id=len(by_url) + 1, url=url, title=title or url, date=date, text=text[:1500])

    for block in blocks:
        btype = getattr(block, "type", "")
        if btype == "web_search_tool_result":
            content = getattr(block, "content", None)
            if isinstance(content, list):  # una lista = resultados; un objeto = error
                for r in content:
                    add(getattr(r, "url", ""), getattr(r, "title", ""), getattr(r, "page_age", None))
        elif btype == "web_fetch_tool_result":
            content = getattr(block, "content", None)
            url = getattr(content, "url", "") if content is not None else ""
            add(url, url)
        elif btype == "text":
            for c in getattr(block, "citations", None) or []:
                add(getattr(c, "url", ""), getattr(c, "title", ""), None, getattr(c, "cited_text", "") or "")
    return list(by_url.values())


def _collect_notes(blocks: list) -> str:
    return "\n".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", "") == "text").strip()
