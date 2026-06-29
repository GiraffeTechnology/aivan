from aivan.intake.rfq_structuring import structure_inquiry_text


def test_structure_chinese_shirt_inquiry():
    structured = structure_inquiry_text("询价5000件格子衬衫，45天交东京，高品质")

    assert structured["quantity"] == 5000
    assert "格子衬衫" in structured["product_name"]
    assert structured["product_category"] == "shirt"
    assert structured["destination"] == "东京"
    assert structured["lead_time_days"] == 45
    assert structured["quality_level"] == "高品质"


def test_structure_chinese_cotton_tshirt_inquiry():
    structured = structure_inquiry_text("帮我询价，1000件纯棉T恤，交加拿大")

    assert structured["quantity"] == 1000
    assert "T恤" in structured["product_name"]
    assert structured["product_category"] == "t-shirt"
    assert structured["material"] == "纯棉"
    assert structured["destination"] == "加拿大"


def test_trace_and_test_prefixes_do_not_affect_structuring():
    structured = structure_inquiry_text("AIVAN-OLLAMA-NATIVE INTAKE-1 询价5000件格子衬衫，45天交东京，高品质")

    assert structured["quantity"] == 5000
    assert structured["destination"] == "东京"
