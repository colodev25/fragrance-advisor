# Fragrance Advisor

Fragrance Advisor is a conversational perfume discovery service for Etualy. It combines a product catalog, semantic search and an AI assistant to help customers find fragrances by notes, style, occasion and budget.

The project includes a FastAPI backend, a browser chat interface, a Shopify catalog pipeline and persistent conversation sessions. Product recommendations are grounded in catalog results, with application logic applying structured constraints before the assistant explains its suggestions.

## Highlights

- Free-form fragrance discovery and a four-step guided consultation
- Semantic product search with price and fragrance-note filtering
- Context-aware follow-up questions and product alternatives
- Persistent sessions stored in SQLite
- Shopify catalog ingestion and a local ChromaDB search index

## Run locally

Uses Python 3.11 in the CI workflow and requires a Groq API key to start the advisor.

```bash
python -m venv .venv
```

Activate the environment, then install the dependencies and configure the API key:

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_api_key_here
```

Start the API:

```bash
uvicorn src.main:app --reload
```

The API listens at `http://127.0.0.1:8000`. Run `python src/reindex.py` before starting it to create a verified catalog/index generation. See [index operations](docs/INDEX_OPERATIONS.md) for updates and Render deployment.

## Project documentation

- [Architecture](docs/ARCHITECTURE.md) — application components and data flow
- [Data pipeline](docs/DATA_PIPELINE.md) — Shopify ingestion and catalog maintenance
- [Search engine](docs/SEARCH_ENGINE.md) — indexing, retrieval and filtering
- [Advisor](docs/ADVISOR.md) — conversation and recommendation behavior
- [API](docs/API.md) — HTTP endpoints and configuration
- [Testing](docs/TESTING.md) — test coverage and execution

## Technology

Python, FastAPI, Groq's OpenAI-compatible API, ChromaDB, SQLite, Shopify JSON products endpoint, and a standalone HTML/CSS/JavaScript chat interface.

## Future improvements

- Evaluate more capable LLMs to improve intent understanding and recommendation explanations.
- Move to an always-on deployment platform or plan to reduce the cold starts currently experienced on Render.
- Add richer search filters, such as brand, fragrance family, availability and more precise price ranges.
