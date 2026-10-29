        "test_accuracy": float(test_accuracy),
        "total_classes": len(clf.classes_),
        "classes": list(clf.classes_),
        "total_samples": len(X),
        "features_dimension": int(X.shape[1]),
        "model_type": "RandomForestClassifier(n_estimators=120)",
        "per_class_metrics": {
            cls: {
                "precision": round(report_dict.get(cls, {}).get("precision", 0.0), 3),
                "recall": round(report_dict.get(cls, {}).get("recall", 0.0), 3),
                "f1_score": round(report_dict.get(cls, {}).get("f1-score", 0.0), 3),
                "support": int(report_dict.get(cls, {}).get("support", 0))
            }
            for cls in clf.classes_ if cls in report_dict
        }
    }
    with open(META_PATH, 'w') as f:
        json.dump(meta, f, indent=2)


    return clf


_LOADED_MODEL = None

def get_recognition_model():
    """Singleton accessor for the loaded classifier."""
    global _LOADED_MODEL
    if _LOADED_MODEL is None:
        if os.path.exists(MODEL_PATH):
            try:
                _LOADED_MODEL = joblib.load(MODEL_PATH)
            except Exception:
                _LOADED_MODEL = train_recognition_model(force_retrain=True)
        else:
            _LOADED_MODEL = train_recognition_model(force_retrain=True)
    return _LOADED_MODEL


# =====================================================================
# 5. REFERENCE SIMILARITY (COSINE / EUCLIDEAN DISTANCE)
# =====================================================================

def calculate_reference_similarity(user_feature_vector, expected_class_id):
    """
    Calculates genuine landmark similarity between learner's captured features
    and the canonical reference template (Requirement 2 & 21).
    Distinguished from model confidence!
    Returns: similarity score 0.0 - 1.0 (float)
    """
    if expected_class_id not in CANONICAL_SIGNS:
        return None

    meta = CANONICAL_SIGNS[expected_class_id]
    base_pts = generate_base_hand_landmarks(meta["finger_states"])
    ref_feat = normalize_single_hand(base_pts)

    # Take static component of user features (first 86 elements)
    user_static = user_feature_vector[:len(ref_feat)]

    # Normalized Cosine similarity
    u_norm = np.linalg.norm(user_static)
    r_norm = np.linalg.norm(ref_feat)
    if u_norm < 1e-4 or r_norm < 1e-4:
        return 0.50

    cos_sim = float(np.dot(user_static, ref_feat) / (u_norm * r_norm))
    # Map from [-1, 1] to [0, 1]
    scaled_sim = max(0.0, min(1.0, (cos_sim + 1.0) / 2.0))
    # Calibrated non-linear scaling for natural hand landmark variance
    calibrated_sim = round(float(scaled_sim ** 1.3), 3)
    return calibrated_sim


# =====================================================================
# 6. INFERENCE & DECISION ENGINE
# =====================================================================

# Configurable thresholds based on validation evidence (Requirement 18)
HIGH_CONFIDENCE_THRESHOLD = 0.60
MINIMUM_RECOGNITION_THRESHOLD = 0.40


def analyze_practice_sign(section_id, expected_sign_input, raw_frames, user=None):
    """
    End-to-end recognition & verification pipeline:
    1. Validates expected sign in section.
    2. Inspects captured frames for hand landmarks.
    3. Normalizes landmarks & extracts sequence features.
    4. Predicts class with genuine model probability.
    5. Calculates reference similarity.
    6. Returns structured response and saves PracticeAttempt.
    """
    from study_companion.models import CourseSection, Lesson, PracticeAttempt

    section = CourseSection.objects.filter(id=section_id).first()
    if not section:
        return {
            "success": False,
            "status": "error",
            "message": "Section not found."
        }

    # Normalize expected sign query
    normalized_input = re.sub(r'\s+', ' ', str(expected_sign_input).strip().lower())
    canonical_expected = TEXT_TO_CANONICAL.get(normalized_input, normalized_input)

    # Check if lesson exists in this section
    sec_lessons = list(section.lessons.all())
    matched_lesson = None
    for l in sec_lessons:
        w_norm = l.word_or_phrase.strip().lower()
        if w_norm == normalized_input or TEXT_TO_CANONICAL.get(w_norm) == canonical_expected:
            matched_lesson = l
            break

    if not matched_lesson:
        return {
            "success": False,
            "status": "not_in_section",
            "message": f"'{expected_sign_input}' is not part of Section {section.section_number}.",
            "expected_sign": expected_sign_input,
            "predicted_sign": None,
            "recognition_confidence": 0.0,
            "matched": False
        }

    # Check if recognition model supports this sign
    if canonical_expected not in CANONICAL_SIGNS or not CANONICAL_SIGNS[canonical_expected].get("is_supported"):
        return {
            "success": True,
            "status": "unsupported",
            "message": "Automatic recognition is not available for this sign yet.",
            "expected_sign": matched_lesson.word_or_phrase,
            "predicted_sign": None,
            "recognition_confidence": 0.0,
            "reference_similarity": None,
            "matched": False,
            "feedback": "You can still use the reference video on the left for self-guided practice."
        }

    # Verify captured frames
    if not raw_frames or not isinstance(raw_frames, list) or len(raw_frames) == 0:
        return {
            "success": True,
            "status": "no_hand",
            "message": "No hand detected. Place your hands clearly inside the camera frame.",
            "expected_sign": matched_lesson.word_or_phrase,
            "predicted_sign": None,
            "recognition_confidence": 0.0,
            "reference_similarity": None,
            "matched": False,
            "feedback": "Keep your hand centered and ensure all 5 fingers are clearly visible.",
            "guidance": "Position your hand within the camera frame so your wrist and all 5 fingertips are visible."
        }

    # Check valid frames with hand landmarks
    valid_frames = []
    for f in raw_frames:
        lms = f if isinstance(f, list) else f.get('landmarks', [])
