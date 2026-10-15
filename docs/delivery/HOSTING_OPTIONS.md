# Opzioni hosting e persistenza

Confronto tecnico preparato il **15 ottobre 2026**. I prezzi sono quelli pubblicati da Render alla data indicata e devono essere confermati nella dashboard dell'account prima di qualsiasi acquisto. Importi in USD, tasse, cambio, banda e minuti di build esclusi.

## Confronto rapido

| Scenario | Configurazione | Costo base indicativo | Sessioni | Disponibilità e limiti |
| --- | --- | --- | --- | --- |
| Demo gratuita | Workspace Hobby + web service Free, `--workers 1`, nessun disco | $0/mese nei limiti inclusi | SQLite effimero: può sparire a ogni sospensione, riavvio o deploy | Sospensione dopo 15 minuti senza traffico; riavvio circa un minuto; 750 ore gratuite mensili per workspace; Render la sconsiglia per produzione |
| Produzione minima da misurare | Workspace Hobby + web service `0.5c-512mb` + disco da 1 GB | circa **$7,25/mese**: $7 compute + $0,25 disco | SQLite in `/var/data/sessions.db`, persistente attraverso riavvii e deploy | Sempre attivo; 0,5 CPU/512 MB; una sola istanza; breve indisponibilità a ogni deploy con disco |
| Produzione con maggiore margine | Workspace Hobby + web service `1c-2g` + disco da 1 GB | circa **$25,25/mese**: $25 compute + $0,25 disco | Come sopra | 1 CPU/2 GB; più margine per modello embedding, indice e richieste concorrenti; stessi limiti del disco |

I prezzi base non comprendono eventuali eccedenze. Il workspace Hobby non ha canone, ma ha limiti propri; una modalità di pagamento può permettere addebiti per banda o pipeline oltre le soglie. Impostare limiti di spesa e notifiche secondo il budget approvato.

## Proposta tecnica

Per la demo aziendale si può mantenere temporaneamente il servizio Free, dichiarando cold start e perdita delle conversazioni ai riavvii. Non va presentato come disponibilità produttiva garantita.

Per il pubblico, mantenendo l'architettura attuale, la soluzione meno invasiva è:

1. un web service Render a pagamento e sempre attivo;
2. un solo processo Uvicorn e una sola istanza;
3. disco dedicato montato in `/var/data`;
4. `SESSIONS_DB_PATH=/var/data/sessions.db` nel Render Environment;
5. indice Chroma costruito durante la build nel percorso attuale, fuori dal disco;
6. `/health` come health check;
7. scelta iniziale del compute solo dopo una prova di memoria e latenza sulla candidata.

Il piano `0.5c-512mb` è il costo minimo da valutare, non una garanzia di capacità. Se caricamento di embedding/Chroma, memoria o latenza non rispettano le soglie approvate, usare almeno `1c-2g`. Non aumentare worker o istanze: lock, sessioni e limiti sono locali al processo.

## Vincoli del disco

- Solo i file sotto il mount path sono persistenti; build e pre-deploy non possono accedere al disco.
- Un servizio con disco non può avere più istanze e perde i deploy senza interruzione: Render arresta la vecchia istanza prima di avviare la nuova.
- Il disco può essere aumentato ma non ridotto; iniziare con la capacità più piccola adatta.
- Render crea snapshot del disco ogni 24 ore e li conserva per almeno sette giorni. La cancellazione di una sessione dal database live non elimina immediatamente le copie negli snapshot: retention e richieste privacy devono descriverlo e approvarlo.
- Ripristinare uno snapshot completo può reintrodurre sessioni scadute o cancellate. Prima di riaprire il servizio occorre rieseguire la pulizia prevista e documentare il recupero.

## Configurazione successiva all'approvazione

```text
Mount path: /var/data
SESSIONS_DB_PATH=/var/data/sessions.db
Build: pip install -r requirements.txt && python src/reindex.py
Start: uvicorn src.main:app --host 0.0.0.0 --port $PORT --workers 1
Health Check: /health
```

Non montare il disco su `/opt/render/project/src`, `chroma_db` o sull'intera directory `data`: l'indice deve rimanere parte della generazione di build e solo le sessioni devono essere scritte nel volume persistente.

## Prove richieste

- Misurare memoria a riposo, durante inizializzazione e con richieste concorrenti simulate.
- Misurare prima risposta a freddo sul Free e risposte a caldo sul piano candidato.
- Creare una sessione fittizia, riavviare e distribuire una nuova build, quindi verificare continuità e scadenza.
- Provare cancellazione/reset, pulizia dopo 24 ore e comportamento WAL con dati fittizi.
- Provare un ripristino in staging e verificare che sessioni scadute/cancellate non vengano rese nuovamente disponibili.
- Registrare indisponibilità durante deploy, commit distribuito, regione, costo effettivo e responsabile.

## Alternative future

Se diventano necessari più worker, più istanze o deploy senza interruzione, SQLite su disco non è più adatto. Occorrono un database condiviso e coordinamento condiviso di lock, idempotenza, rate limit e budget Groq. È una revisione architetturale separata, non una semplice sostituzione del percorso del database.

Fonti verificate: [Render Free](https://render.com/docs/free), [piani compute](https://render.com/docs/compute-plans), [prezzi](https://render.com/pricing), [dischi persistenti](https://render.com/docs/disks), [deploy](https://render.com/docs/deploys).
