# Arquitectura

```mermaid
flowchart LR
    U[Formulario Streamlit<br/>nombre + desambiguadores<br/>monto + fuente declarada] --> S

    subgraph Datos públicos
        OFAC[(OFAC SDN + alias)]
        ONU[(Lista consolidada ONU)]
        ENAHO[(ENAHO 2024<br/>módulo 500)]
        BCRP[(API BCRP<br/>tipo de cambio)]
        WEB[(Web pública peruana<br/>Infogob, El Peruano, gob.pe, medios)]
    end

    S[1 · Sanciones<br/>rapidfuzz] --> O
    OFAC --> S
    ONU --> S
    O[2 · OSINT<br/>Claude + web_search] --> X
    WEB --> O
    FX[Fixtures sintéticos] -. modo sintético .-> X
    X[3 · Extracción estructurada<br/>Claude + pydantic<br/>identidad × relevancia] --> W
    W[4 · Monto tope plausible<br/>Python] --> R
    ENAHO --> W
    BCRP --> W
    R[5 · Reglas de riesgo<br/>Python] --> N
    N[6 · Redacción con citas<br/>Claude + pydantic] --> D[Borrador KYC<br/>pantalla + .docx]
```

| Paso | Archivo | ¿LLM? | Por qué así |
|---|---|---|---|
| Sanciones | `kyc/sanctions.py` | No | Es binario y auditable: listas oficiales y similitud difusa con umbral visible |
| OSINT | `kyc/osint.py` | Sí | Buscar y leer fuentes heterogéneas es justo lo que un LLM con búsqueda hace bien |
| Extracción | `kyc/llm.py`, `kyc/schemas.py` | Sí | Juzgar si una nota habla de la misma persona y si importa requiere criterio; la salida es JSON validado |
| Monto tope | `kyc/wealth.py` | No | Los números no se le piden al LLM: salen de la ENAHO y de supuestos visibles |
| Riesgo | `kyc/risk.py` | No | Reglas explícitas que un oficial de cumplimiento puede revisar y defender ante el regulador |
| Redacción | `kyc/llm.py` | Sí | Convierte hallazgos en prosa de compliance, citando cada fuente |
