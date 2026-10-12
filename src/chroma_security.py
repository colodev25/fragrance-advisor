"""Validate raw persisted settings before Chroma can instantiate an embedder.

Compatible with the pinned Chroma 1.5.9 model; recheck on any Chroma upgrade.
Filesystem access to the database remains an operator responsibility.
"""


def _validate_embedding(embedding, placeholder=False):
    if placeholder and embedding == {"type": "unknown"}:
        return  # Chroma's unused sparse-vector placeholder cannot build a model.
    if not isinstance(embedding, dict) or set(embedding) != {"type", "name", "config"}:
        raise RuntimeError("Configurazione embedding Chroma non autorizzata.")
    parameters = embedding["config"]
    if embedding["type"] != "known" or not isinstance(parameters, dict):
        raise RuntimeError("Configurazione embedding Chroma non autorizzata.")
    if embedding["name"] == "default":
        allowed = parameters == {}
    elif embedding["name"] == "onnx_mini_lm_l6_v2":
        allowed = (set(parameters) <= {"preferred_providers"}
                   and parameters.get("preferred_providers") in (None, [], ["CPUExecutionProvider"]))
    else:
        allowed = False
    if not allowed:
        raise RuntimeError("Configurazione embedding Chroma non autorizzata.")


def _validate_schema(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "embedding_function":
                _validate_embedding(item, placeholder=True)
            else:
                _validate_schema(item)
    elif isinstance(value, list):
        for item in value:
            _validate_schema(item)


def validate_local_embedding(collection):
    config = collection.configuration_json
    if not isinstance(config, dict):
        raise RuntimeError("Configurazione embedding Chroma non verificabile.")
    _validate_embedding(config.get("embedding_function"))
    # Read raw schema JSON, never collection.schema/configuration (deserializers).
    schema = getattr(collection._model, "serialized_schema", None)
    if schema is not None and not isinstance(schema, dict):
        raise RuntimeError("Schema Chroma non verificabile.")
    _validate_schema(schema)
