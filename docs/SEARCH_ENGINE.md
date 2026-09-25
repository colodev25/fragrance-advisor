# Search Engine

## Overview

The semantic search system is implemented in:

```text
src/search.py
```

It provides the retrieval layer used by `FragranceAdvisor` to identify perfumes relevant to a user's request.

The system combines:

* product data from `catalog.json`;
* multilingual text embeddings;
* ChromaDB;
* semantic similarity;
* additional deterministic filtering.

## Architecture

```text
User request
     ↓
Search query
     ↓
Sentence Transformer
     ↓
Query embedding
     ↓
ChromaDB
     ↓
Semantic candidates
     ↓
Price / availability filtering
     ↓
Relevant products
```

## Embeddings

The current implementation uses:

```text
paraphrase-multilingual-MiniLM-L12-v2
```

This model produces multilingual embeddings and is therefore suitable for queries and product descriptions written in different languages.

The same embedding space is used to compare the user's query with the semantic representations of products.

## ChromaDB

ChromaDB acts as the vector database for the perfume catalog.

Each indexed product is associated with:

* a product identifier;
* its semantic text;
* metadata used by the application.

The collection is configured to use cosine similarity/distance.

Conceptually:

```text
catalog.json
     ↓
semantic_text
     ↓
Embedding
     ↓
ChromaDB collection
```

## Semantic Search

A search request is performed through the search engine interface.

The main search parameters include:

```text
query
min_price
max_price
n_results
```

The query is converted into an embedding and compared with the embeddings stored in ChromaDB.

The result is a set of products ordered according to semantic relevance.

## Candidate Over-Fetching

The advisor does not necessarily use only the first result returned by the vector database.

Instead, the search layer can retrieve a larger candidate set and subsequently apply deterministic filters.

For example:

```text
User query
    ↓
Semantic search
    ↓
12 candidates
    ↓
Additional filtering
    ↓
Final candidates
```

This approach allows the application to combine semantic similarity with business constraints such as price or availability.

## Price Filtering

Price constraints can be applied independently of semantic similarity.

This allows the system to search for semantically relevant products while respecting a user's budget.

For example:

```text
Semantic relevance
        +
Price constraint
        ↓
Filtered candidates
```

The final filtering strategy is controlled by the advisor layer.

## Role in the Advisor

The search engine does not generate the final conversational response.

Its responsibility is retrieval.

The overall architecture is therefore:

```text
             ┌─────────────────┐
             │  User request   │
             └────────┬────────┘
                      ↓
             ┌─────────────────┐
             │     Advisor     │
             └────────┬────────┘
                      ↓
             ┌─────────────────┐
             │  Search Engine  │
             └────────┬────────┘
                      ↓
             ┌─────────────────┐
             │    ChromaDB     │
             └────────┬────────┘
                      ↓
                Candidates
                      ↓
             ┌─────────────────┐
             │     Advisor     │
             └────────┬────────┘
                      ↓
                    LLM
                      ↓
                  Response
```

This separation keeps retrieval and natural-language generation as distinct responsibilities.

## Current Status

> 🚧 The semantic search implementation is currently used by the advisor and may be further refined as the project evolves.

Changes to the embedding model, product representation, filtering strategy or vector database configuration may affect recommendation quality.
