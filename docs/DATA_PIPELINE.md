# Data Pipeline

## Overview

The data pipeline transforms product information into the structured catalog consumed by the fragrance advisor and the semantic search engine.

The pipeline is divided into two main stages:

```text
Product Source
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

The ingestion and indexing stages are intentionally separated.

---

## 1. Product Ingestion

The ingestion process is implemented in:

```text
src/ingest.py
```

It retrieves product information from the configured product source and processes the returned data.

The pipeline can handle:

- product information;
- pricing;
- availability;
- tags;
- descriptions;
- olfactory pyramid;
- fragrance family;
- usage information;
- product URLs.

---

## 2. Data Cleaning

Raw product data can contain HTML, encoded entities and inconsistent whitespace.

The ingestion pipeline normalizes this information before creating the final product representation.

The resulting data is structured so that it can be consumed consistently by the search and advisor layers.

---

## 3. Olfactory Data Extraction

The ingestion process extracts or constructs the fragrance's olfactory pyramid.

The structure is:

```json
{
  "top": [],
  "heart": [],
  "base": []
}
```

The resulting notes can subsequently be used by:

- semantic search;
- explicit note matching;
- recommendation logic.

---

## 4. Catalog Output

The main processed catalog is stored in:

```text
data/catalog.json
```

Additional datasets are used for products that are unavailable or rejected during processing:

```text
data/out_of_stock.json
data/scartati.json
```

---

## 5. Semantic Indexing

Catalog generation and vector indexing are separate operations.

After updating `catalog.json`, the semantic index can be rebuilt with:

```bash
python src/reindex.py
```

This produces the ChromaDB representation used by the search engine.

Therefore, a complete catalog refresh follows:

```bash
python src/ingest.py
python src/reindex.py
```

---

## Data Flow

The complete process can be summarized as:

```text
External Product Source
          │
          ▼
     Data Retrieval
          │
          ▼
     Data Cleaning
          │
          ▼
  Olfactory Extraction
          │
          ▼
     catalog.json
          │
          ▼
      Reindexing
          │
          ▼
       ChromaDB
          │
          ▼
    Search / Advisor
```

---

## Data Separation

The pipeline keeps different classes of products separated:

| File                | Purpose                             |
| ------------------- | ----------------------------------- |
| `catalog.json`      | Main searchable product catalog     |
| `out_of_stock.json` | Products currently unavailable      |
| `scartati.json`     | Products excluded during processing |

This allows the application to distinguish between searchable products and products that should not participate in recommendations.

---

## Updating the Catalog

When product information changes:

1. Run the ingestion pipeline.
2. Verify the generated catalog.
3. Rebuild the semantic index.
4. Restart the application if required.

Example:

```bash
python src/ingest.py
python src/reindex.py
uvicorn src.main:app --reload
```

---

## Relationship with the Search Engine

The data pipeline is responsible for creating the data consumed by the search layer.

```text
DATA PIPELINE
     │
     ▼
catalog.json
     │
     ▼
SEARCH ENGINE
     │
     ▼
ChromaDB
```

The pipeline itself does not perform conversational recommendations.

That responsibility belongs to `FragranceAdvisor`.
