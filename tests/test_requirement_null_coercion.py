"""AIVAN-001: null-field coercion for real LLM providers.

Real providers (Qwen / OpenAI / ...) frequently emit ``null`` for optional
fields instead of omitting them. Fields whose Pydantic type does not accept
``None`` (e.g. ``material_spec: str = ""``) would otherwise raise a
ValidationError. ``_coerce_nulls`` rewrites those nulls to each field's
declared default while leaving genuinely optional fields untouched.

Coverage:
1. null string fields -> "" (material_spec, tolerance, surface_finish, ...)
2. null bool field -> False (cad_attachment)
3. a full null payload constructs BuyerRequirement without ValidationError
4. non-null values are preserved unchanged
5. truly optional (default None) fields keep None
6. keys not declared on the model are ignored
"""
from aivan.agents.requirement_agent import _coerce_nulls
from aivan.schemas.requirement import BuyerRequirement


def test_null_string_fields_coerced_to_empty_string():
    raw = {
        "material_spec": None,
        "tolerance": None,
        "surface_finish": None,
        "process_type": None,
        "notes": None,
    }
    coerced = _coerce_nulls(raw, BuyerRequirement)
    assert coerced["material_spec"] == ""
    assert coerced["tolerance"] == ""
    assert coerced["surface_finish"] == ""
    assert coerced["process_type"] == ""
    assert coerced["notes"] == ""


def test_null_bool_field_coerced_to_false():
    coerced = _coerce_nulls({"cad_attachment": None}, BuyerRequirement)
    assert coerced["cad_attachment"] is False


def test_qwen_style_full_null_payload_validates():
    """A payload with every reported null field constructs without error."""
    raw = {
        "product_type": "industrial gloves",
        "quantity": 1000,
        "material_spec": None,
        "tolerance": None,
        "surface_finish": None,
        "cad_attachment": None,
        "process_type": None,
        "notes": None,
    }
    coerced = _coerce_nulls(raw, BuyerRequirement)
    req = BuyerRequirement(**coerced)  # must not raise ValidationError
    assert req.material_spec == ""
    assert req.tolerance == ""
    assert req.surface_finish == ""
    assert req.process_type == ""
    assert req.notes == ""
    assert req.cad_attachment is False
    assert req.quantity == 1000
    assert req.product_type == "industrial gloves"


def test_non_null_values_preserved():
    raw = {
        "material_spec": "100% cotton",
        "cad_attachment": True,
        "quantity": 5000,
    }
    coerced = _coerce_nulls(raw, BuyerRequirement)
    assert coerced["material_spec"] == "100% cotton"
    assert coerced["cad_attachment"] is True
    assert coerced["quantity"] == 5000


def test_optional_none_fields_kept_as_none():
    """Fields whose default is None (e.g. quantity) stay None — they are valid."""
    raw = {"quantity": None, "gsm": None, "target_unit_price": None, "delivery_days": None}
    coerced = _coerce_nulls(raw, BuyerRequirement)
    assert coerced["quantity"] is None
    assert coerced["gsm"] is None
    assert coerced["target_unit_price"] is None
    assert coerced["delivery_days"] is None
    # And it still validates.
    BuyerRequirement(**coerced)


def test_unknown_keys_ignored():
    """Keys not declared on the model are passed through untouched, no error."""
    raw = {"not_a_real_field": None, "material_spec": None}
    coerced = _coerce_nulls(raw, BuyerRequirement)
    assert coerced["not_a_real_field"] is None  # left as-is
    assert coerced["material_spec"] == ""


def test_list_factory_field_coerced():
    """A null for a default_factory list field becomes an empty list."""
    coerced = _coerce_nulls({"missing_fields": None}, BuyerRequirement)
    assert coerced["missing_fields"] == []
