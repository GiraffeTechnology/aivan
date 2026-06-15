from __future__ import annotations
from aivan.risk.models import SupplierRiskReport

def format_risk_report_text(report: SupplierRiskReport) -> str:
    lines = [
        f"=== SUPPLIER RISK REPORT ===",
        f"Supplier: {report.supplier_name}",
        f"Report ID: {report.report_id}",
        f"Created: {report.created_at}",
        f"",
        f"RISK LEVEL: {report.risk_score.risk_level.upper()}",
        f"Risk Score: {report.risk_score.risk_score:.2f} / 1.0",
        f"Confidence: {report.risk_score.confidence_score:.2f} / 1.0",
        f"Evidence Items: {report.risk_score.evidence_count}",
        f"",
        f"RECOMMENDED ACTION: {report.risk_score.recommended_action}",
        f"",
    ]
    if report.risk_score.positive_signals:
        lines.append("POSITIVE SIGNALS:")
        for s in report.risk_score.positive_signals:
            lines.append(f"  + {s}")
        lines.append("")
    if report.risk_score.risk_flags:
        lines.append("RISK FLAGS:")
        for f in report.risk_score.risk_flags:
            lines.append(f"  ! {f}")
        lines.append("")
    if report.risk_score.missing_evidence:
        lines.append("MISSING EVIDENCE (not yet checked):")
        for m in report.risk_score.missing_evidence:
            lines.append(f"  ? {m}")
        lines.append("")
    lines.append("NOTE: Absence of negative evidence is NOT proof of safety. This report is for human review only.")
    return "\n".join(lines)

def should_block_supplier(report: SupplierRiskReport) -> bool:
    import os
    block_critical = os.environ.get("AIVAN_BLOCK_CRITICAL_RISK_SUPPLIERS", "false").lower() == "true"
    return block_critical and report.risk_score.risk_level == "critical"
