# Dossier tecnico di consegna

Preparato il **15 ottobre 2026**. Questi documenti sono versionabili e contengono solo informazioni tecniche condivisibili. Preparazione documentale non significa collaudo superato o autorizzazione alla pubblicazione.

| Documento | Uso |
| --- | --- |
| [RELEASE.md](RELEASE.md) | Perimetro, versione di riferimento, blocchi e condizioni di rilascio |
| [CONFIGURATION.md](CONFIGURATION.md) | Ambiente locale, variabili, Render, GitHub e account |
| [DATA_FLOW.md](DATA_FLOW.md) | Trattamenti effettivi, storage, conservazione e punti da validare |
| [OPERATIONS.md](OPERATIONS.md) | Installazione, catalogo, incidenti, recupero e manutenzione |
| [HOSTING_OPTIONS.md](HOSTING_OPTIONS.md) | Confronto demo/produzione, costi Render, persistenza e prove richieste |
| [NETWORK_ACCESS.md](NETWORK_ACCESS.md) | Origini, proxy, policy del tema e passaggio sicuro degli accessi |
| [COMMERCIAL_REVIEW.md](COMMERCIAL_REVIEW.md) | Regole di raccomandazione e campione da approvare con l'azienda |
| [CAPACITY_REVIEW.md](CAPACITY_REVIEW.md) | Modelli, limiti interni, misure e soglie di capacità da concordare |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Piano di collaudo compilabile con criteri di superamento |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Inventario preliminare e verifica dei diritti/licenze |

Per iniziare consulta la scheda di release, completa la configurazione e segui le procedure operative e il piano di collaudo del dossier. Per la configurazione iniziale usa [`.env.example`](../../.env.example), mai una copia di credenziali reali.

## Pubblico e privato

- Qui conservare procedure, modelli vuoti, architettura e risultati tecnici realmente anonimizzati.
- In `delivery-private/`, esclusa da Git, compilare decisioni, persone, costi, accordi, inventario accessi, verbali firmati ed evidenze riservate. La cartella è locale: non arriva con un clone Git.
- Il documento preesistente `DECISIONI_AZIENDA.md` resta privato; il registro nuovo ne permette l'approvazione puntuale senza sostituirlo.
- Password e token non vanno neppure nei documenti privati: usare un gestore password con condivisione controllata.
- `.gitignore` non cifra i file, non impedisce un'aggiunta forzata e non rimuove file già pubblicati. Questa cartella di progetto è sotto OneDrive: concordare anche accessi/sincronizzazione del deposito privato o spostarlo in un deposito aziendale approvato.

## Convenzioni

**VERIFICATO NEL CODICE**: osservato nel repository; **DICHIARATO**: comunicato dal proprietario; **DA VERIFICARE**: manca prova nell'ambiente; **DA APPROVARE**: occorre una decisione aziendale. `NON ESEGUITO` e `NON APPLICABILE` non equivalgono a `SUPERATO`.

Il dossier descrive lo stato alla data indicata. Aggiornare versione, riferimenti e verbali dopo ogni modifica della candidata. Eventuali documenti firmati hanno una loro versione immutabile; non sovrascriverli con bozze successive.
