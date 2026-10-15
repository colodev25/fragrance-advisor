# Manuale operativo

Stato: procedura predisposta il 15 ottobre 2026; prove da registrare in [ACCEPTANCE.md](ACCEPTANCE.md). Responsabili e recapiti si compilano nel dossier privato. Per configurazioni vedere [CONFIGURATION.md](CONFIGURATION.md).

## Installazione e aggiornamento

1. Identificare commit/tag candidato, configurazione backend e Liquid corrispondente. Eseguire suite e audit della candidata, conservando gli esiti.
2. Verificare catalogo disponibile e build indice. Non eseguire ingest per una modifica esclusivamente grafica.
3. Distribuire il backend nel servizio di staging o nella finestra concordata. Verificare commit servito, `/health` e `/catalog/status`. Un health verde non verifica Groq né l'intero percorso di acquisto.
4. In Shopify duplicare il tema effettivo, assegnando un nome che identifichi la candidata. Inserire `snippets/etualy-advisor.liquid` e una sola chiamata `{% render 'etualy-advisor' %}` nel layout appropriato, normalmente prima di `</body>`.
5. Verificare CORS, proxy e CSP seguendo [NETWORK_ACCESS.md](NETWORK_ACCESS.md), poi percorso chat, varianti, drawer e contenuti già presenti nel carrello. L'anteprima Shopify può modificare il carrello del browser: usare una sessione di prova senza concludere pagamenti.
6. Dopo accettazione pubblicare il tema/configurazione approvati. Aggiornamento backend e widget devono restare compatibili, soprattutto per il contratto delle sessioni.
7. Verificare subito dopo pubblicazione un percorso reale autorizzato; registrare versione, risultato e eventuale ripristino. Sostituire anche lo snippet DevTools locale per le prove successive.

Non pubblicare per errore l'intera copia del tema se nel frattempo l'azienda ha modificato il tema live: confrontare le differenze e coordinare la finestra di pubblicazione con chi lo gestisce.

## Dove impostare la configurazione

| Destinazione | Valori | Regola operativa |
| --- | --- | --- |
| `.env` locale ignorato da Git | Variabili di `.env.example`, solo quando servono alle prove | Crearlo senza sovrascrivere configurazioni esistenti; non copiarlo nel materiale pubblico |
| Render Environment | `GROQ_API_KEY`, modelli chat, `ALLOWED_ORIGINS`, limiti API/Groq e, quando disponibile un disco, `SESSIONS_DB_PATH` | Impostare prima dell'avvio dell'applicazione e registrare privatamente owner e data della modifica |
| GitHub Actions Secrets | `GROQ_API_KEY` per enrichment e `SHOPIFY_STORE_URL` per i workflow che la leggono | Usare segreti del repository/ambiente aziendale; non inserirli nei file YAML |
| Sorgente del widget | Endpoint pubblico, `EARLY_WAKE_ENABLED`, `FEEDBACK_PREVIEW_ENABLED` e identificatore `data-widget-version` | Mantenere allineati HTML, Liquid e snippet; questi controlli non sono gestiti da `.env` |

L'elenco completo, i default e le variabili deprecate sono in [CONFIGURATION.md](CONFIGURATION.md). Una modifica ai modelli o a `ALLOWED_ORIGINS` richiede riavvio/deploy perché questi valori vengono letti durante l'importazione dell'applicazione.

## Catalogo

| Operazione | Esecuzione dalla root | Effetto |
| --- | --- | --- |
| Sincronizzazione locale | `python src/ingest.py` | Legge Shopify e aggiorna dataset/coda; nessuna inferenza enrichment |
| Arricchimento autorizzato | `python -m src.catalog_jobs --max-products 30 --token-budget 40000 --max-minutes 20` | Può consumare quota Groq e scrive progressi |
| Indicizzazione | `python src/reindex.py` | Nuova generazione dal catalogo locale; primo download modello possibile |
| Caricamento nuova generazione | Riavviare il backend secondo procedura | Il processo in esecuzione mantiene la generazione caricata finché non viene riavviato |

In produzione preferire i workflow già configurati: leggere summary/artifact, controllare eventuali cali anomali e confrontare hash report con `/catalog/status`. L'arricchimento incompleto non deve impedire l'aggiornamento di prezzo/stock. Il monitor controlla l'ultimo import riuscito e segnala oltre 72 ore; non attesta la conclusione dei job correnti.

## Gestione incidenti

| Sintomo | Prima verifica | Azione | Condizione di recupero |
| --- | --- | --- | --- |
| `/health` 503 | Log inizializzazione, catalogo/indice e variabili | Correggere causa o ripristinare versione compatibile; non lanciare ingest indiscriminatamente | Health verde e prova chat controllata |
| Chat 429 | Quota modello, budget processo, Retry-After | Rispettare cooldown; controllare job enrichment e quota organizzazione | Richiesta riuscita dopo attesa prevista |
| Chat 503 con health verde | Saturazione o provider indisponibile | Leggere codice errore; ridurre concorrenza/carico, evitare aumenti alla cieca | Percorso chat recuperabile e carico nei limiti |
| Catalogo vecchio | Ultimo artifact sync, errore job, hash servito | Correggere import/deploy e rieseguire il job pertinente | Import recente e hash coerente |
| Aggiunta carrello incerta | Esito Shopify e carrello effettivo | Non ripetere automaticamente l'aggiunta; invitare alla verifica | Quantità corretta senza duplicati |
| Drawer non aggiornato | Tema/versione e adattatore `cart:build` | Verificare contratto Impulse in anteprima | Drawer e contatore coerenti |
| Chiave esposta | Dove pubblicata e ambienti che la usano | Revocare/sostituire, aggiornare ambienti, valutare accessi e conservare evidenze riservate | Vecchia chiave revocata, nuova provata |
| Possibile violazione dati | Accessi/log pertinenti senza diffusione ulteriore | Avvisare subito il referente aziendale, contenere e seguire la procedura approvata | Decisione del responsabile incidente e verifica tecnica |

Non inviare trascrizioni o credenziali in issue pubbliche. Obblighi di notifica e comunicazione in caso di incidente vanno gestiti dall'azienda con il consulente competente; il manutentore fornisce evidenze e tempi documentati.

## Disattivazione e rollback

1. Per fermare il widget, rimuovere/commentare la chiamata Liquid nel tema concordato e verificare che il negozio resti utilizzabile. Questo non elimina le conversazioni server né chiude widget già caricati nelle schede aperte.
2. Per un rollback backend, individuare una coppia backend/widget precedentemente collaudata e verificare compatibilità di schema, catalogo e configurazione. Scegliere il deploy precedente nel pannello o il commit approvato seguendo il processo di rilascio.
3. Se l'API va disattivata subito, intervenire anche sull'hosting secondo autorizzazione; la rimozione della bolla non interrompe client già aperti o richieste dirette.
4. Per l'indice seguire [INDEX_OPERATIONS.md](../INDEX_OPERATIONS.md). In un nuovo ambiente effimero possono mancare le generazioni precedenti: ricostruire da catalogo valido.
5. Per sessioni persistenti, usare backup SQLite coerenti e compatibili. Provare ripristino in staging, con dati fittizi. Non reintrodurre sessioni scadute o già cancellate in violazione della retention approvata.
6. Registrare ora, motivo, versioni, dati interessati, controlli dopo recupero e chi ha autorizzato. Non cancellare evidenze dell'incidente per ripulire i log.

## Rotazione credenziali e manutenzione

- Generare una nuova credenziale nell'account aziendale autorizzato, aggiornare Render/GitHub interessati, provare il servizio, revocare quella precedente. In caso di esposizione la revoca può dover precedere il ripristino.
- Controllare notifiche job, errori, quote e freschezza secondo la frequenza concordata; verificare che anche il sostituto riceva gli avvisi.
- Rivalutare dipendenze ed eccezioni prima di ogni rilascio e alla scadenza; aggiornare lock insieme agli input.
- Ripetere i casi carrello/accessibilità dopo aggiornamenti del tema; ripetere campione qualità e consumi dopo cambio modello.
- Conservare backup/evidenze solo per la durata concordata. Verificare periodicamente accessi e revoche.

## Passaggio di gestione

- [ ] Referente primario e sostituto hanno accesso alle dashboard necessarie.
- [ ] Ricezione di un allarme provata in staging.
- [ ] Disattivazione e ripristino dimostrati da una seconda persona.
- [ ] Manuale, versioni e deposito riservato consegnati.
- [ ] Accessi residui dello sviluppatore concordati e scadenza registrata.
