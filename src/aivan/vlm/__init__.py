"""Vision-language model (VLM) provider boundary.

Kept as a thin, policy-gated seam. The private-domain RFQ baseline never depends
on VLM provider APIs; visual QC / image reasoning is a controlled escalation.
"""
