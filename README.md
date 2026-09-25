# Fragrance Advisor

> AI-powered conversational assistant for personalized fragrance discovery.

Fragrance Advisor is an AI-powered assistant designed to help customers discover perfumes based on their preferences, needs and context.

The system combines **natural-language conversation**, **semantic search** and **structured fragrance data** to generate personalized recommendations for an e-commerce environment.

---

## ✨ Features

* 💬 Conversational fragrance discovery
* 🌸 Personalized perfume recommendations
* 🧠 Semantic search over the product catalog
* 🎯 Guided and free-form conversation modes
* 💰 Budget and price constraints
* 🧴 Product context and alternative suggestions
* 🌿 Olfactory notes and fragrance families
* 🌐 FastAPI backend for website integration

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
   └── LLM + Conversation Logic
   │
   ▼
Personalized Recommendations
```

The advisor interprets the customer's request, retrieves relevant fragrances from the catalog, applies deterministic constraints such as price, and uses the resulting product context to generate the final response.

---

## 🛠️ Tech Stack

| Area            | Technologies                    |
| --------------- | ------------------------------- |
| Backend         | Python, FastAPI, Pydantic       |
| AI              | Groq, OpenAI-compatible API     |
| Semantic Search | ChromaDB, Sentence Transformers |
| Frontend        | HTML, CSS, JavaScript           |
| Data            | JSON                            |

---

## 📁 Project Structure

```text
fragrance-advisor/
│
├── data/              # Product datasets
│
├── docs/              # Project documentation
│   ├── ADVISOR.md
│   ├── API.md
│   ├── ARCHITECTURE.md
│   ├── DATA_PIPELINE.md
│   └── SEARCH_ENGINE.md
│
├── src/
│   ├── advisor.py     # Recommendation engine
│   ├── ingest.py      # Data ingestion
│   ├── main.py        # FastAPI application
│   └── search.py      # Semantic search
│
├── index.html         # Web interface
├── requirements.txt
├── .gitignore
└── README.md
```

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

### 5. Start the backend

```bash
uvicorn src.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

---

## 📚 Documentation

The detailed technical documentation is organized by component:

| Document                                   | Description                                  |
| ------------------------------------------ | -------------------------------------------- |
| **[Architecture](docs/ARCHITECTURE.md)**   | System structure and component relationships |
| **[Data Pipeline](docs/DATA_PIPELINE.md)** | Product ingestion and data processing        |
| **[Search Engine](docs/SEARCH_ENGINE.md)** | Semantic search and vector retrieval         |
| **[Advisor](docs/ADVISOR.md)**             | Conversation and recommendation logic        |
| **[API](docs/API.md)**                     | Backend endpoints and API usage              |

The README provides a high-level overview, while the documentation contains the implementation details.

---

## 📌 Project Status

**Development — `feature/new-site`**

The project is currently being adapted for integration with a new website.

Core components such as the conversational advisor, semantic search and backend API are implemented, while the integration and other project components are still under development and refinement.

---

## 🔮 Future Improvements

* Recommendation quality improvements
* More advanced preference modeling
* Expanded product filtering
* Frontend integration improvements
* Automated testing and evaluation
* Performance and scalability improvements
* Production deployment configuration

---

## 🔐 Security

API credentials and other secrets must be stored in environment variables and must not be committed to Git.

The `.env` file is excluded from version control through `.gitignore`.

---

## 📄 License

This project currently does not specify a public open-source license.
