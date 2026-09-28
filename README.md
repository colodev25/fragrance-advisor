# Fragrance Advisor

> AI-powered conversational assistant for personalized fragrance discovery.

Fragrance Advisor is an AI-powered assistant designed to help customers discover perfumes based on their preferences, needs and context.

The system combines **natural-language conversation**, **semantic search**, **structured fragrance data** and **LLM-based reasoning** to generate personalized recommendations for an e-commerce environment.

---

## ✨ Features

- 💬 Conversational fragrance discovery
- 🌸 Personalized perfume recommendations
- 🧠 Semantic search over the product catalog
- 🎯 Guided and free-form conversation modes
- 💰 Budget and price constraints
- 🧴 Product context and alternative suggestions
- 🌿 Olfactory notes and fragrance families
- 💾 Persistent conversation sessions
- 🌐 FastAPI backend for website integration
- 🧪 Unit, integration and end-to-end testing

---

## 🧠 How It Works

```text
Customer
   │
   ▼
Web Interface
   │
   ▼
FastAPI API
   │
   ▼
FragranceAdvisor
   │
   ├── Semantic Search ──► ChromaDB
   │
   ├── LLM ──────────────► Groq
   │
   └── Session Store ────► SQLite
   │
   ▼
Personalized Recommendations
```

The advisor interprets the customer's request, retrieves relevant fragrances, applies deterministic constraints and uses the resulting context to generate the final response.

---

## 🛠️ Tech Stack

| Area            | Technologies                    |
| --------------- | ------------------------------- |
| Backend         | Python, FastAPI, Pydantic       |
| AI              | Groq, OpenAI-compatible API     |
| Semantic Search | ChromaDB, Sentence Transformers |
| Frontend        | HTML, CSS, JavaScript           |
| Persistence     | SQLite                          |
| Data            | JSON                            |
| Testing         | pytest                          |

---

## 📁 Project Structure

```text
fragrance-advisor/
│
├── data/
│   ├── catalog.json
│   ├── out_of_stock.json
│   └── scartati.json
│
├── docs/
│   ├── ADVISOR.md
│   ├── API.md
│   ├── ARCHITECTURE.md
│   ├── DATA_PIPELINE.md
│   ├── SEARCH_ENGINE.md
│   └── TESTING.md
│
├── src/
│   ├── advisor.py
│   ├── ingest.py
│   ├── main.py
│   ├── reindex.py
│   ├── search.py
│   └── session_store.py
│
├── tests/
│   ├── test_api.py
│   ├── test_parsers.py
│   ├── test_scenarios_e2e.py
│   └── test_session_store.py
│
├── index.html
├── pytest.ini
├── requirements.txt
├── .gitignore
└── README.md
```

> `sessions.db` is generated locally by the application and should not be committed to version control.

---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/colodev25/fragrance-advisor.git
cd fragrance-advisor
```

To work on the current development branch:

```bash
git checkout feature/new-site
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

On Windows:

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root containing the required API credentials.

```env
GROQ_API_KEY=your_api_key_here
```

> ⚠️ Never commit `.env` or API keys to the repository.

### 5. Prepare the product catalog

If the catalog needs to be updated, run the ingestion pipeline:

```bash
python src/ingest.py
```

Then rebuild the semantic search index:

```bash
python src/reindex.py
```

### 6. Start the backend

```bash
uvicorn src.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

---

## 🧪 Testing

The project includes unit, API, session persistence and end-to-end tests.

Run the test suite with:

```bash
pytest
```

For details about the available test categories and scenarios, see the testing documentation.

---

## 📚 Documentation

The detailed technical documentation is organized by component:

| Document                                   | Description                                    |
| ------------------------------------------ | ---------------------------------------------- |
| **[Architecture](docs/ARCHITECTURE.md)**   | System structure and component relationships   |
| **[Data Pipeline](docs/DATA_PIPELINE.md)** | Product ingestion and data processing          |
| **[Search Engine](docs/SEARCH_ENGINE.md)** | Semantic retrieval and result processing       |
| **[Advisor](docs/ADVISOR.md)**             | Conversation, recommendation and session logic |
| **[API](docs/API.md)**                     | Backend endpoints and API usage                |
| **[Testing](docs/TESTING.md)**             | Test structure, scenarios and execution        |

The README provides a high-level overview, while the documentation contains the implementation details.

---

## 📌 Project Status

**Development — `feature/new-site`**

The project is currently being developed and adapted for integration with a new website.

The main conversational, search, persistence and API components are implemented, while the integration and other project components continue to evolve.

The documentation describes the current implementation and may change together with the codebase.

---

## 🔮 Future Improvements

- Expanded recommendation evaluation
- More advanced fragrance preference modeling
- Additional product filtering
- Improved frontend integration
- Expanded test coverage
- Automated CI testing
- Performance and scalability improvements
- Production deployment configuration

---

## 🔐 Security

API credentials and other secrets must be stored in environment variables and must not be committed to Git.

The `.env` file and local session database are excluded from version control through `.gitignore`.

If a credential is accidentally exposed, it should be revoked and regenerated immediately.

---

## 📄 License

This project currently does not specify a public open-source license.
