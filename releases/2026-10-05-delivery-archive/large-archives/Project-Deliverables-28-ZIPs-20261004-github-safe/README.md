# Project-Deliverables-28-ZIPs-20261004-github-safe: GitHub-safe archive parts

Download all 17 ZIP parts and the adjacent manifest, checksums and reassembly script into one directory. Each part is an ordinary valid ZIP containing one consecutive binary segment. These are packaging parts, not independent installation packages.

Run `python3 reassemble.py` in that directory. It checks every wrapper and segment, reconstructs `Project-Deliverables-28-ZIPs-20261004-github-safe.zip`, and verifies the complete SHA-256 and byte size before placing the output. The script uses only the Python standard library. Alternatively verify `sha256sum --check SHA256SUMS`, extract every wrapper, and concatenate its `parts/` files in numeric order.

- Reassembled size: 140706518 bytes
- Reassembled SHA-256: `b44385cf974dae8f991ec3fb45983edd29abf0bcf1a87f96289aa37ca5e74da4`
- Original handoff SHA-256: `cc92e07c6f2dcd3d123eba05083bcc996f546d6eb36767744b61e4524b4159a8`

The reconstructed ZIP is the frozen GitHub-safe mirror. It is not byte-identical to the private original. Read its publication notice, omissions and current-copy checksums. Historical checksums labelled HISTORICAL-REFERENCE are provenance, not current-copy validation commands. Preserve all candidate and historical status labels; this archive is not a release, CI, deployment or genuine-device acceptance claim.
