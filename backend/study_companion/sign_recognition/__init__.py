
# =====================================================================
# 8. LAZY TEMPORAL SEQUENCE MODEL IMPORT
# Keep PyTorch out of Django startup unless explicitly requested.
# =====================================================================

_TEMPORAL_EXPORTS = {
    "CONTROLLED_VOCABULARY",
    "ISLTemporalSequenceClassifier",
    "load_temporal_recognition_model",
    "extract_temporal_sequences_from_frames",
    "run_temporal_sign_recognition",
    "TOKEN_TO_CONCEPT_MAP",
    "SEQUENCE_LENGTH",
    "FEATURE_DIM",
}


def __getattr__(name):
    if name not in _TEMPORAL_EXPORTS:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )

    from importlib import import_module

    temporal_model = import_module(
        "study_companion.temporal_model"
    )
    value = getattr(temporal_model, name)

    # Cache the imported attribute to avoid repeated imports.
    globals()[name] = value
    return value
