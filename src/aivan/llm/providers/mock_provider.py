from aivan.llm.base import LLMProvider

MOCK_RESPONSES = {
    "requirement_structuring": {
        "category": "apparel",
        "product_type": "men's shirt",
        "quantity": 10000,
        "quantity_unit": "pcs",
        "fabric_material": "100% cotton",
        "gsm": 180,
        "color": "white",
        "size_ratio": "S/M/L/XL=20/40/30/10",
        "packaging": "single poly bag",
        "destination": "Vancouver",
        "target_unit_price": 4.80,
        "target_currency": "USD",
        "delivery_days": 45,
        "incoterms": "DDP",
        "logistics_preference": "air",
        "missing_fields": [],
        "confidence": 0.95,
        "language": "zh",
    },
    "missing_field_clarification": {
        "missing_fields": [
            {"field_name": "gsm", "description": "Fabric weight", "question": "面料克重/GSM？"},
            {"field_name": "size_ratio", "description": "Size breakdown", "question": "尺码比例？"},
            {"field_name": "packaging", "description": "Packaging", "question": "包装方式？"},
            {"field_name": "target_unit_price", "description": "Target price", "question": "目标单价？"},
            {"field_name": "incoterms", "description": "Trade terms", "question": "物流条款（FOB/DDP）？"},
        ],
        "message_text": "已收到您的询盘。为了帮您准确询价，还需要确认：\n1. 面料克重/GSM？\n2. 尺码比例？\n3. 包装方式？\n4. 目标单价或预算？\n5. 物流条款偏好（FOB/DDP）？",
        "confidence": 0.9,
    },
    "supplier_inquiry_drafting": {
        "message_text": "Dear Supplier,\n\nWe are looking to source 10,000 pcs white 100% cotton men's shirts (180gsm), size ratio S/M/L/XL=20/40/30/10, single poly bag packaging.\n\nDestination: Vancouver, Canada\nTarget delivery: 45 days\nIncoterms: DDP preferred\nTarget price: USD 4.80/pc or below\n\nPlease confirm:\n1. Unit price and MOQ\n2. Production capacity and lead time\n3. Fabric availability\n4. Sample availability and fee\n\nThank you.",
        "confidence": 0.9,
    },
    "supplier_response_parsing": {
        "unit_price": 4.50,
        "currency": "USD",
        "moq": 5000,
        "capacity_per_day": 500,
        "capacity_per_month": 12000,
        "lead_time_days": 35,
        "material_availability": "In stock",
        "qc_commitment": "Inline + final QC",
        "logistics_note": "FOB Guangzhou",
        "incoterms": "FOB",
        "payment_terms": "30% deposit, 70% before shipment",
        "risks": [],
        "missing_info": [],
        "confidence": 0.85,
    },
    "buyer_option_generation": {
        "options": [
            {"option_label": "Option A — Fastest", "option_type": "fastest", "reasoning": "Fastest confirmed supplier, meets 45-day deadline with 3-day buffer.", "risk_level": "low"},
            {"option_label": "Option B — Lowest Cost", "option_type": "lowest_cost", "reasoning": "Best price at USD 4.20/pc but lead time is 50 days, exceeds your deadline.", "risk_level": "medium"},
            {"option_label": "Option C — Most Reliable", "option_type": "safest", "reasoning": "Highest quality and delivery score with verified factory.", "risk_level": "low"},
        ]
    },
    "marketplace_search_query_generation": {
        "queries": [
            "white cotton men's shirt 180gsm manufacturer MOQ 10000",
            "100% cotton men's shirt factory 180gsm bulk order",
            "白色 纯棉 男士 衬衣 180gsm 工厂 10000件",
            "男士衬衫 纯棉 180gsm 外贸 工厂",
        ]
    },
    "supplier_risk_search_planning": {
        "supplier_name_queries": ["Example Supplier Co Ltd company profile China"],
        "platform_store_queries": ["Example Supplier Co Ltd 1688 storefront reviews"],
        "complaint_queries": ["Example Supplier Co Ltd complaints scam fraud"],
        "litigation_queries": ["Example Supplier Co Ltd legal dispute lawsuit"],
        "certification_queries": ["Example Supplier Co Ltd ISO certificate factory audit"],
        "product_category_queries": ["Example Supplier Co Ltd men's shirt cotton quality"],
        "address_contact_queries": ["Example Supplier Co Ltd Guangzhou address contact"],
        "sanctions_or_restriction_queries": ["Example Supplier Co Ltd sanctions blacklist OFAC"],
        "reason": "Unknown supplier discovered through marketplace search",
    },
    "supplier_risk_report_generation": {
        "risk_level": "medium",
        "risk_score": 0.4,
        "confidence_score": 0.6,
        "positive_signals": ["Active platform storefront", "Professional product images"],
        "risk_flags": ["storefront_new_or_low_history", "capacity_claim_unverified"],
        "recommended_action": "contact_but_verify",
        "notes": "New supplier with limited history. Request business license and factory video before placing order.",
    },
    "gpm_quote_analysis": {
        "human_approval_required": True,
        "recommendation": "human_review_required",
        "quote_position": "within_mid_range",
        "confidence": "medium",
        "reasoning": "Mock GPM analysis — review supplier quote manually.",
        "runtime_status": "mock",
    },
    "default": {"result": "ok", "confidence": 0.8, "message_text": "Mock response generated."},
}

class MockLLMProvider(LLMProvider):
    provider_name = "mock"

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, schema_hint: dict, temperature: float = 0.0) -> dict:
        task_lower = task.lower().replace("-", "_").replace(" ", "_")
        for key in MOCK_RESPONSES:
            if key != "default" and key in task_lower:
                return dict(MOCK_RESPONSES[key])
        return dict(MOCK_RESPONSES["default"])
