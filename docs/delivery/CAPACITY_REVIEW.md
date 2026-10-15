# Modelli AI, quote e capacità: piano di misura

Scheda preparata il 15 ottobre 2026. I valori in codice sono limiti interni, non quote garantite da Groq né prestazioni misurate. Registrare i risultati effettivi e le schermate dell'account nel dossier riservato, senza messaggi, credenziali o identificativi dei clienti.

## Configurazione osservata

| Componente | Valore attuale nel repository | Significato |
| --- | --- | --- |
| Chat, modello primario | `openai/gpt-oss-120b` come default | Può essere sostituito da `GROQ_PRIMARY_MODEL` in Render |
| Chat, fallback | `openai/gpt-oss-20b` come default | Può essere sostituito da `GROQ_FALLBACK_MODEL` |
| Arricchimento catalogo | `openai/gpt-oss-20b` nel workflow | Job distinto, ma può consumare quota della stessa organizzazione |
| Richieste chat/reset contemporanee | `2` per processo | Oltre il limite: `503 service_capacity_exceeded`, con `Retry-After: 2` |
| Chiamate modello chat | `20` al minuto per processo | Include tentativi; non coincide con richieste utente o quota globale provider |
| Chat per visitatore | `30` al minuto | Limite locale basato sull'IP normalizzato; proxy da verificare |
| Reset per visitatore | `10` al minuto | Limite locale distinto |
| Arricchimento pianificato | massimo 30 prodotti, 40.000 token riservabili, 20 minuti | Massimali del job, non consumo reale garantito |

Il backend registra la durata in millisecondi delle richieste POST ammesse e i codici dei rifiuti di capacità. Il job produce `catalog_enrichment_report.json` come artifact con prenotazioni e token effettivi disponibili. Le quote di organizzazione/modello, il piano e i consumi effettivi vanno letti nella console Groq dell'account in uso. Una seconda chiave della stessa organizzazione non va trattata come capacità aggiuntiva senza conferma del provider.

## Raccolta minima

Per una finestra di prova annotare: commit/versione, piano Render, modello, giorno e intervallo, numero di richieste chat, mediana/p95 dei tempi, errori `429` e `503` per codice, chiamate e token Groq disponibili, memoria massima del servizio, andamento del job catalogo. Separare misure **simulate** da chiamate Groq **reali**. Aggregare i dati, non archiviare body, trascrizioni, `session_key`, header di autenticazione o indirizzi IP completi.

1. Eseguire prima i test locali con provider simulato: una e due richieste concorrenti, saturazione a tre, timeout, cooldown e risposta del widget. Usare soltanto sessioni fittizie.
2. Dopo aver verificato la quota disponibile, usare un piccolo campione reale autorizzato di domande fittizie. Annotare tempi e consumi separando chat e arricchimento; interrompere la prova se si raggiunge la soglia concordata.
3. Valutare il catalogo durante la finestra del job pianificato: i due usi possono condividere la quota Groq. Non dedurre capacità di picco dai soli log di un periodo senza traffico.
4. Confrontare risultati con le soglie approvate prima di cambiare modello, numero di worker, ammissioni o piano hosting. Ripetere il campione dopo ogni cambio rilevante.

## Comportamento da confermare nel collaudo

| Situazione | Comportamento atteso |
| --- | --- |
| Terza richiesta contemporanea | Rifiuto rapido e controllato, senza coda lunga; widget permette di riprovare |
| Limite per visitatore | `429` con `Retry-After`; il widget comunica l'attesa senza perdere la bozza |
| Quota o cooldown Groq | Errore controllato e nuova prova dopo l'attesa indicata; nessuna promessa di risposta immediata |
| Provider indisponibile o risposta non valida | Messaggio recuperabile, niente prodotto inventato come risposta certa |
| Arricchimento esaurisce budget | Job conclude con report e riprende la coda secondo le regole del catalogo; disponibilità chat da verificare separatamente |

## Decisioni da concordare

- Numero atteso di consulenze simultanee e orari di picco.
- Tempo di risposta accettabile: mediana, p95 e prima risposta con servizio sospeso o appena avviato.
- Percentuale massima accettabile di errori di capacità/provider in una finestra definita.
- Budget mensile e soglia d'avviso, anche se pari a zero; destinatario e sostituto.
- Piano di crescita: prima ottimizzare e misurare, poi valutare modello, quota o hosting diversi.

Riportare le soglie in [ACCEPTANCE.md](ACCEPTANCE.md) e le approvazioni nel dossier privato. I controlli T25 e T32 verificano rispettivamente capacità API e job del catalogo.
