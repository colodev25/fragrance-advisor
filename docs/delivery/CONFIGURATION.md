# Configurazione riproducibile

Riferimento: 15 ottobre 2026. I valori indicati come default descrivono il codice; quelli proposti per produzione richiedono conferma. Non copiare segreti in questo file.

## Avvio locale

1. Installare Python indicato in `.python-version` e Node in `.node-version` per i test browser.
2. Creare un ambiente Python isolato e installare `requirements/dev.txt` per sviluppo, oppure `requirements.txt` per il solo runtime.
3. Se `.env` esiste, integrarlo manualmente senza sovrascriverlo. Altrimenti copiare `.env.example` in `.env` e compilare la chiave Groq solo per prove reali autorizzate.
4. Preparare un indice dal catalogo locale con `python src/reindex.py`. Il primo utilizzo può scaricare il modello di embedding; non è una sincronizzazione Shopify.
5. Avviare dalla root con `python -m uvicorn src.main:app --env-file .env --host 127.0.0.1 --port 8000 --workers 1`. Il caricamento esplicito evita che alcune variabili siano lette prima di `.env`.
6. `/health` verifica l'inizializzazione. Il widget contiene oggi un URL remoto fisso: avviare il backend locale non fa usare automaticamente quello locale al widget. Per una prova locale modificare l'endpoint nella sola copia di collaudo e servire la pagina via HTTP; poi ripristinare la configurazione prevista per la consegna.

## Variabili

| Variabile | Esempio/default | Dove e perché |
| --- | --- | --- |
| `GROQ_API_KEY` | vuoto nel modello | Segreto Render per chat; GitHub Secret per enrichment; `.env` locale solo se necessario |
| `SHOPIFY_STORE_URL` | `https://etualy.com` | URL negozio: ambiente ingest/GitHub Secret già usato dal workflow |
| `GROQ_PRIMARY_MODEL` | `openai/gpt-oss-120b` | Ambiente backend, prima dell'import |
| `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-20b` | Ambiente backend, prima dell'import |
| `ALLOWED_ORIGINS` | Esempio locale: localhost/127.0.0.1 porta 8000 | Produzione proposta: `https://etualy.com,https://www.etualy.com`; aggiungere soltanto preview necessarie |
| `SESSIONS_DB_PATH` | `data/sessions.db` | File SQLite; proposta con disco: `/var/data/sessions.db` |
| `RATE_LIMIT_ENABLED` | `true` | Tenere attivo |
| `CHAT_RATE_LIMIT_PER_MINUTE` | `30` | Limite per client, non capacità globale |
| `RESET_RATE_LIMIT_PER_MINUTE` | `10` | Limite per client |
| `API_MAX_BODY_BYTES` | `16384` | Limite richieste chat/reset |
| `API_BODY_TIMEOUT_SECONDS` | `5` | Termine per ricezione corpo |
| `API_MAX_CONCURRENT_REQUESTS` | `2` | Ammissioni combinate; non aumentare senza misure |
| `GROQ_CHAT_CALLS_PER_MINUTE` | `20` | Budget locale al processo per chiamate modello, inclusi tentativi |
| `GROQ_CHAT_COOLDOWN_SECONDS` | `5` | Ripiego per cooldown provider |
| `GROQ_CATALOG_MODEL` | `openai/gpt-oss-20b` | Arricchimento; workflow lo specifica esplicitamente |
| `GROQ_CATALOG_MAX_TOKENS` | `2048` | Budget risposta enrichment; non quota mensile |
| `GROQ_CATALOG_INTERVAL_SECONDS` | `2` | Intervallo enrichment |

`FORWARDED_ALLOW_IPS` è una configurazione Uvicorn; Render documenta `*` come default Python, ma valore e comportamento effettivi vanno verificati sul servizio prima di approvare i limiti per IP. La procedura è in [NETWORK_ACCESS.md](NETWORK_ACCESS.md). `RATE_LIMIT_TRUST_PROXY_HEADERS` è ignorata e non va usata. I limiti chat e catalogo non sostituiscono le quote aggregate dell'organizzazione Groq.

La scadenza sessione di 24 ore e il budget cooperativo chat di 25 secondi sono attualmente costanti nel codice, non variabili disponibili in `.env`. Il widget attende al massimo 60 secondi per la risposta completa. Non creare impostazioni fittizie per cambiarli.

## Render

- Build: `pip install -r requirements.txt && python src/reindex.py`.
- Start: `uvicorn src.main:app --host 0.0.0.0 --port $PORT --workers 1`.
- Health Check: `/health`.
- Auto-Deploy: `After CI Checks Pass`, da controllare sul servizio/branch effettivo.
- Se approvato un disco: montarlo su un percorso dedicato alle sessioni; non sovrapporlo a `chroma_db` o al catalogo di build.
- Registrare privatamente regione, piano, costi, owner, retention dei log e proxy verificati.
- Prima di cambiare piano o aggiungere un disco consultare [HOSTING_OPTIONS.md](HOSTING_OPTIONS.md); la configurazione corrente resta Free finché non esiste approvazione aziendale.

## GitHub e separazione account

I workflow catalogo puntano a `feature/new-site`; le definizioni pianificate devono esistere anche nel branch predefinito. Per cambiare branch di produzione aggiornare insieme checkout, push, dispatch, concurrency e impostazioni Render, poi collaudare il percorso completo.

| Workflow | Credenziali applicative | Frequenza letta nei file |
| --- | --- | --- |
| `tests.yml` | Nessuna | Push/PR e dispatch |
| `security.yml` | Nessuna | Eventi pertinenti, dispatch e lunedì 05:22 UTC |
| `catalog-sync.yml` | `SHOPIFY_STORE_URL` | Controllo quotidiano 02:04 UTC; import a giorni alterni Roma |
| `catalog-enrich.yml` | `GROQ_API_KEY` | Ogni giorno 02:39 UTC; 30 prodotti, 40.000 token riservabili, 20 minuti |
| `catalog-monitor.yml` | Token GitHub automatico | Ogni giorno 03:17 UTC |

Le quote enrichment sono massimali del job, non consumo garantito. I token automatici GitHub sono forniti dai workflow; non creare un PAT personale senza necessità. Per gli orari prendere i file YAML come riferimento: altri documenti storici possono riportare pianificazioni precedenti.

La candidata espone l'identificatore `2026.10-rc2` nell'attributo `data-widget-version` dell'elemento `#oaWidget`, identico in `index.html`, nel Liquid e nello snippet locale. Il feedback dimostrativo è disattivato nel sorgente con `FEEDBACK_PREVIEW_ENABLED = false`. Il risveglio preventivo è controllato nel sorgente da `EARLY_WAKE_ENABLED = true`; impostandolo a `false` non vengono creati il relativo timestamp né la richiesta `/health` prima della chat. Entrambi sono flag di build, non variabili d'ambiente: una modifica richiede aggiornamento coordinato delle tre varianti e nuovo collaudo.
