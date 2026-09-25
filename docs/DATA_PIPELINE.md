# Data Pipeline

## Overview

The data pipeline prepares the perfume catalog used by Fragrance Advisor.

The main implementation is contained in:

```text
src/ingest.py
```

The resulting datasets are stored in:

```text
data/
├── catalog.json
├── out_of_stock.json
└── scartati.json
```

The pipeline can be summarized as:

```text
Shopify
   ↓
Download products
   ↓
Clean and normalize data
   ↓
Extract product information
   ↓
Extract olfactory pyramid
   ↓
Generate semantic representation
   ↓
Classify product
   ↓
Save catalog
```

## Source Data

The current ingestion process retrieves products from a Shopify store through its product JSON endpoint.

The process supports pagination so that large catalogs can be processed in multiple requests.

Each Shopify product is transformed into the internal representation used by the application.

## Data Cleaning

Product information can contain HTML markup and formatting artifacts.

The ingestion pipeline cleans textual information before storing it.

The cleaning process includes:

* removal of HTML markup;
* HTML entity decoding;
* normalization of whitespace;
* removal of unnecessary formatting;
* extraction of meaningful textual content.

This produces cleaner input for both structured extraction and semantic search.

## Olfactory Pyramid

One of the main purposes of the ingestion pipeline is to reconstruct the perfume's olfactory structure.

The internal representation distinguishes:

```text
Top notes
Heart notes
Base notes
```

The extraction process attempts to identify these sections from the product information.

When structured information is not available or cannot be extracted reliably, fallback mechanisms are used.

The pipeline can use the product description and an LLM-based extraction process to recover olfactory information from narrative descriptions.

## Product Enrichment

Products are enriched with additional fields used by the advisor and search engine.

The internal representation may contain information such as:

```text
id
name
brand
sku
price
currency
in_stock
tags
olfactory_pyramid
family
ptype
usage_profile
description
urls
semantic_text
```

The exact available fields depend on the information successfully extracted from the source product.

## Semantic Representation

The `semantic_text` field is particularly important for the semantic search layer.

Instead of searching only individual fields such as product name or notes, the system creates a textual representation of the product that combines relevant information.

This representation is subsequently embedded by the search engine.

Conceptually:

```text
Product data
     ↓
Structured information
     ↓
semantic_text
     ↓
Embedding
     ↓
Vector database
```

## Output Files

### `catalog.json`

Contains the structured catalog used by the search engine.

This is the main dataset consumed during normal advisor operation.

### `out_of_stock.json`

Stores products identified as unavailable or out of stock.

These products can be separated from the active catalog so that unavailable items are not treated as normal recommendations.

### `scartati.json`

Stores products that are excluded from the usable catalog during the ingestion process.

This provides a record of products that could not be processed or did not satisfy the requirements of the pipeline.

## Relationship with Search

Once the catalog has been generated, `search.py` loads the products and creates the searchable representation used by ChromaDB.

Therefore, the ingestion pipeline is upstream of the semantic search system:

```text
ingest.py
    ↓
catalog.json
    ↓
search.py
    ↓
ChromaDB
```

Changes to the structure or content of `catalog.json` can therefore affect search quality and advisor behavior.

## Current Status

> 🚧 The ingestion pipeline is part of the current development architecture.

The extraction and enrichment process may evolve as the source website and product data structure are finalized.
