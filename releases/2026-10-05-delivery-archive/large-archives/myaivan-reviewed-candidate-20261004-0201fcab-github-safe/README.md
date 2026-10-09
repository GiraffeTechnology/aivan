# myaivan-reviewed-candidate-20261004-0201fcab-github-safe: GitHub-safe archive parts

Download all 15 ZIP parts and the adjacent manifest, checksums and reassembly script into one directory. Each part is an ordinary valid ZIP containing one consecutive binary segment. These are packaging parts, not independent installation packages.

Run `python3 reassemble.py` in that directory. It checks every wrapper and segment, reconstructs `myaivan-reviewed-candidate-20261004-0201fcab-github-safe.zip`, and verifies the complete SHA-256 and byte size before placing the output. The script uses only the Python standard library. Alternatively verify `sha256sum --check SHA256SUMS`, extract every wrapper, and concatenate its `parts/` files in numeric order.

- Reassembled size: 118236350 bytes
- Reassembled SHA-256: `96f1bcbe6ab523cdfac48ecf4a3bd25f4837deda7ffe590ccc017baee8ef2e12`
- Original handoff SHA-256: `207eb59550b897d03d9cae601f22e5a03831340ff78222189a21b723b99fd22b`

The reconstructed ZIP is the frozen GitHub-safe mirror. It is not byte-identical to the private original. Read its publication notice, omissions and current-copy checksums. Historical checksums labelled HISTORICAL-REFERENCE are provenance, not current-copy validation commands. Preserve all candidate and historical status labels; this archive is not a release, CI, deployment or genuine-device acceptance claim.
