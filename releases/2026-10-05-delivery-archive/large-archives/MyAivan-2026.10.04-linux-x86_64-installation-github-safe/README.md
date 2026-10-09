# MyAivan-2026.10.04-linux-x86_64-installation-github-safe: GitHub-safe archive parts

Download all 14 ZIP parts and the adjacent manifest, checksums and reassembly script into one directory. Each part is an ordinary valid ZIP containing one consecutive binary segment. These are packaging parts, not independent installation packages.

Run `python3 reassemble.py` in that directory. It checks every wrapper and segment, reconstructs `MyAivan-2026.10.04-linux-x86_64-installation-github-safe.zip`, and verifies the complete SHA-256 and byte size before placing the output. The script uses only the Python standard library. Alternatively verify `sha256sum --check SHA256SUMS`, extract every wrapper, and concatenate its `parts/` files in numeric order.

- Reassembled size: 111811759 bytes
- Reassembled SHA-256: `1b37eee6bff2a92bb7163d0bf7fa0620b723aa2bdb4d8b4e22bd83c8ac84b4b0`
- Original handoff SHA-256: `3bd0c328a1ea0496ccc14939a5ab9fca710a0bb13d305ec1044712b2596191e3`

The reconstructed ZIP is the frozen GitHub-safe mirror. It is not byte-identical to the private original. Read its publication notice, omissions and current-copy checksums. Historical checksums labelled HISTORICAL-REFERENCE are provenance, not current-copy validation commands. Preserve all candidate and historical status labels; this archive is not a release, CI, deployment or genuine-device acceptance claim.
