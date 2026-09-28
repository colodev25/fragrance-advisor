# Search Engine

## Overview

Fragrance Advisor uses semantic search to retrieve fragrance candidates from the product catalog.

The search system combines vector similarity with deterministic processing such as price filtering and lexical relevance.

This allows natural-language requests to be matched against product information even when the exact words used by the customer are not present in the product name.

---

## Components

The search layer is primarily implemented through:

```text
src/search.py
src/reindex.py
```

The two modules have different responsibilities.

### `search.py`

Handles product retrieval during application runtime.

### `reindex.py`

Builds the ChromaDB index from the current `catalog.json`.

---

## Indexing Pipeline

The catalog and vector index are generated through separate steps:

```text
Product Data
     │
     ▼
 ingest.py
     │
     ▼
catalog.json
     │
     ▼
reindex.py
     │
     ▼
ChromaDB
```

This separation makes it possible to update product data without coupling ingestion directly to runtime search.

---

## Embeddings

The system uses a multilingual Sentence Transformer model:

```text
paraphrase-multilingual-MiniLM-L12-v2
```

The model converts semantic product representations into numerical vectors.

This is particularly useful for multilingual natural-language queries and descriptions.

---

## Product Representation

Products are indexed using their semantic representation together with structured metadata.

Relevant information can include:

- product name;
- brand;
- price;
- availability;
- fragrance family;
- olfactory pyramid;
- usage profile;
- product URL;
- semantic text.

The semantic representation provides the textual context used by the embedding model.

---

## Runtime Search

A simplified runtime flow is:

```text
User Query
    │
    ▼
Semantic Embedding
    │
    ▼
ChromaDB Retrieval
    │
    ▼
Candidate Pool
    │
    ├──► Price Filtering
    │
    └──► Lexical / Note Processing
    │
    ▼
Relevant Candidates
```

The search layer can retrieve additional candidates before applying deterministic processing.

This over-fetching approach allows the advisor to work with a larger candidate pool rather than immediately limiting the result set.

---

## Semantic Similarity

Semantic retrieval is based on vector similarity rather than exact string matching.

For example, a request such as:

```text
"Vorrei qualcosa di fresco e marino per l'estate"
```

can retrieve products whose descriptions or semantic representations express similar characteristics even when they do not contain the exact same sentence.

---

## Deterministic Filtering

Semantic similarity alone is not sufficient for constraints that require exact logic.

The system can therefore apply deterministic filters after retrieval.

Examples include:

- maximum price;
- availability;
- explicit note requirements;
- product metadata.

This creates a hybrid retrieval process:

```text
Semantic Retrieval
       +
Deterministic Filtering
       +
Lexical Relevance
       ↓
Final Candidate Set
```

---

## Explicit Note Matching

When a user explicitly requests a fragrance note, the advisor can apply additional note-oriented processing.

This is useful for queries where the presence of a specific ingredient or olfactory characteristic is a strong requirement.

The process can consider information contained in:

- top notes;
- heart notes;
- base notes;
- fragrance family;
- product name;
- semantic description.

---

## Reindexing

The semantic index can be rebuilt with:

```bash
python src/reindex.py
```

The reindexing process uses the current `data/catalog.json` as its source.

A typical catalog update therefore follows:

```bash
python src/ingest.py
python src/reindex.py
```

The first command updates the catalog, while the second rebuilds the search index.

---

## ChromaDB

ChromaDB is used as the vector database for fragrance retrieval.

The application maintains a fragrance collection containing:

- product identifiers;
- semantic documents;
- product metadata;
- embeddings.

The exact storage configuration is handled by the indexing and search components.

---

## Search and Recommendation

The search engine does not directly generate the final conversational answer.

Instead:

```text
Search Engine
      │
      ▼
Candidate Fragrances
      │
      ▼
FragranceAdvisor
      │
      ▼
LLM
      │
      ▼
Conversational Response
```

This separation allows retrieval and response generation to evolve independently.
