# Scheda di release e perimetro

**Stato: preparazione della consegna, pubblicazione non autorizzata da questo documento.**

| Campo | Valore |
| --- | --- |
| Progetto | Fragrance Advisor / Etualy Olfactive Advisor |
| Data della scheda | 15 ottobre 2026 |
| Branch locale esaminato | `feature/new-site` |
| Commit di base esaminato | `922b9f156bf404f79f3273bd74495e4aa0eeb591` |
| Tag/versione definitiva | DA ASSEGNARE dopo collaudo |
| Commit definitivo consegnato | DA REGISTRARE; quello sopra precede questi documenti |
| Backend configurato nel widget | `https://fragrance-advisor-api.onrender.com` |
| Negozio previsto | `https://etualy.com` |
| Tema destinazione / ID / versione | DA CONFERMARE nel pannello Shopify |
| Runtime dichiarati dai file | Python 3.11, Node 24.19.0 per gli strumenti browser |
| Hosting comunicato | Render Free, senza disco; stato dashboard DA VERIFICARE |
| Modalità attuale d'uso sul negozio comunicata | Prova con DevTools; installazione definitiva a cura dell'azienda |

## Funzioni incluse

- Consulenza guidata e chat libera, ricerca sul catalogo e preferenze di raccomandazione.
- Schede con dettagli, note strutturate/narrative disponibili e formati verificati con Shopify.
- Aggiunta al carrello confermata dal negozio e adattatore per aggiornamento drawer Impulse; da validare sulla versione effettiva del tema.
- Stato della conversazione nella stessa scheda del browser, credenziale di sessione e recupero controllato dopo errori/perdita dei dati server.
- Avviso AI, pannello tecnico privacy, supporto tastiera/mobile e gestione errori.
- Sincronizzazione, arricchimento progressivo, monitor di freschezza e test automatizzati.
- Richiesta preventiva `/health` dopo caricamento pagina e all'apertura se trascorso l'intervallo; massimo una ogni dieci minuti per scheda quando lo storage è disponibile, altrimenti per pagina. Non è un timer di mantenimento continuo.

## Funzioni escluse dalla prima release

- Raccolta e salvataggio dei feedback, dashboard e attribuzione degli acquisti. La schermata stelle esistente è soltanto un'anteprima in memoria e verrà disabilitata nella versione pubblica prima del collaudo finale.
- Nuovi filtri di ricerca, funzioni personalizzate e ulteriori dati di catalogo non necessari ai percorsi approvati.
- Migrazione dell'hosting, secondo provider AI o cambio di modello motivati soltanto come evoluzione: verranno valutati se misure di qualità, quota, costo o prestazioni ne dimostreranno la necessità.
- Garanzie di accuratezza sanitaria o SLA di disponibilità non ancora concordati.
- Nessuna garanzia di conservazione delle sessioni attraverso i riavvii del servizio Free.
- Più worker/istanze richiedono coordinamento condiviso prima dell'abilitazione.

## Condizioni aperte prima dell'attivazione

| ID | Condizione | Stato / prova richiesta |
| --- | --- | --- |
| RLS-01 | Informativa, ruoli, retention, fornitori e scelte cookie/storage | DA APPROVARE; dossier privato |
| RLS-02 | Allergie/dati sanitari R02 | Rinviato nella revisione precedente; riesame e correzione con prove necessari |
| RLS-03 | Piano hosting, capacità, persistenza e costi | DA APPROVARE e misurare |
| RLS-04 | CORS, proxy, CSP e privilegi account | DA VERIFICARE nell'ambiente effettivo |
| RLS-05 | Compatibilità del tema, dispositivi e accessibilità | Eseguire matrice di accettazione |
| RLS-06 | Licenze/diritti e regole commerciali | DA VALIDARE con azienda |
| RLS-07 | Suite, audit e nuova richiesta preventiva | Eseguire sulla candidata definitiva; non usare vecchi risultati come prova corrente |
| RLS-08 | Eccezioni Chroma | Rivalutare `tools/security/exceptions.json`; scadenza registrata 12 novembre 2026 |
| RLS-09 | Allarmi, recupero e referente assistenza | Provare ricezione e procedura |
| RLS-10 | Comportamento pubblico dei feedback | Decisione del proprietario 15/10/2026: disabilitare la schermata nella prima release; modifica e test ancora da eseguire |

Global ZDR Groq e deploy Render dopo CI sono **dichiarati attivati dal proprietario**; non sono stati verificati in dashboard durante la stesura.

## Perimetro approvato dal proprietario del progetto

Il 15 ottobre 2026 il proprietario ha confermato il perimetro sopra descritto: la prima release comprende consulenza, catalogo, schede/formati, carrello verificato, continuità e resilienza, interfaccia desktop/mobile, avviso AI e procedure operative. Feedback persistente, attribuzione acquisti, nuovi filtri e cambi infrastrutturali non dimostrati necessari restano evoluzioni successive. Questa conferma definisce lo sviluppo della candidata; l'azienda deve comunque accettare perimetro, condizioni operative e pubblicazione.

## Materiale da consegnare

- Sorgenti e lock corrispondenti al commit/tag definitivo; Liquid dello stesso rilascio.
- Documentazione tecnica e istruzioni di avvio; `.env.example` senza segreti.
- Verbale compilato, rapporti test/audit, limitazioni accettate e riferimenti agli accordi, tramite canale riservato quando necessario.
- Accessi individuali e responsabilità trasferiti; istruzioni di aggiornamento/disattivazione.

Escludere dal pacchetto pubblico `.env`, sessioni SQLite, log di clienti, cache, ambienti virtuali, credenziali e dossier privato. L'archivio Git da solo non include i file ignorati: il materiale riservato va consegnato separatamente.

## Decisione finale

- [ ] Candidata identificata e provata sul tema previsto.
- [ ] Condizioni obbligatorie chiuse; eccezioni motivate e approvate.
- [ ] Verbale di accettazione firmato/approvato con versione identificabile.
- [ ] Autorizzazione esplicita all'attivazione e responsabile del rilascio.

Esito attuale: **dossier predisposto, collaudo e approvazione finale da completare**.
